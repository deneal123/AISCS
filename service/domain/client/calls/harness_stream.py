"""Grant/receipt wrapper around the existing provider stream implementation."""

from contextlib import aclosing

from service.domain.client.protocol import PinSource
from service.domain.execution.context import current_execution
from service.shared.harness_protocol import HarnessFailure, TranscriptMessage

from .harness_state import capture_state, restore_state


async def provider_stream(client, provider_name, messages, model, parameters, send_native):
    from service.domain.client.providers.gigachat.images import native_image_messages

    async def send(operation_id):
        async with native_image_messages(client, provider_name, messages) as native:
            async with aclosing(
                send_native(
                    client, provider_name, native, model, harness_call_id=operation_id, **parameters
                )
            ) as stream:
                async for delta in stream:
                    yield delta

    async with aclosing(
        paid_stream(
            send, provider=provider_name, model=model, messages=messages, parameters=parameters
        )
    ) as stream:
        async for delta in stream:
            yield delta


async def paid_stream(send, *, provider, model, messages, parameters):
    execution = current_execution()
    client = execution.harness if execution is not None else None
    if client is None:
        async with aclosing(send(None)) as stream:
            async for delta in stream:
                yield delta
        return
    payload = {
        "messages": messages,
        "model": model,
        **{
            key: parameters[key]
            for key in ("tools", "tool_choice", "max_tokens", "temperature")
            if key in parameters
        },
    }
    operation_id, cached = await client.before_call(provider, model, payload)
    state = parameters["round_state"]
    session = parameters.get("provider_session") or execution.provider_session
    parts = []
    receipt_attempted = False
    try:
        if cached:
            from service.infrastructure.harness.call_payload import receipt_finish_reason

            restore_state(session, cached, provider=provider, model=model)
            message = TranscriptMessage.model_validate(cached["message"])
            state.prompt, state.completion = cached["prompt"], cached["completion"]
            state.total = state.prompt + state.completion
            state.tool_calls = [{"id": call.id, **call.function} for call in message.tool_calls]
            state.finish_reason = receipt_finish_reason(cached)
            if session is not None:
                session.complete_round(
                    provider=provider,
                    model=model,
                    usage=state.usage(),
                    call_id=operation_id,
                    source=PinSource.STREAM_DELTA,
                )
            if message.content:
                yield message.content
        else:
            async with aclosing(send(operation_id)) as stream:
                async for delta in stream:
                    parts.append(delta)
                    yield delta
            message = TranscriptMessage(
                role="assistant",
                content="".join(parts),
                tool_calls=[
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                    for call in state.tool_calls
                ],
            )
            receipt_attempted = True
            await client.complete_call(
                operation_id,
                usage=state.usage(),
                message=message,
                finish_reason=state.finish_reason,
                provider_state=capture_state(session, provider=provider, model=model),
            )
        execution.usage.record_usage(
            state.usage(), provider=provider, model=model, kind="chat", receipt_id=operation_id
        )
        if client.failure:
            raise HarnessFailure(client.failure)
    except BaseException:
        if not cached and not receipt_attempted:
            await client.fail_call(operation_id)
        raise
