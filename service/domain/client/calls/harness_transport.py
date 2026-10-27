"""Paid-call boundary: durable grant before transport, receipt before continuation."""

from contextlib import contextmanager
from contextvars import ContextVar

from openai.types.chat import ChatCompletion

from service.domain.execution.context import current_execution
from service.shared.harness_protocol import HarnessFailure, TranscriptMessage

from .harness_state import capture_state, restore_state

_KIND = ContextVar("harness_usage_kind", default="chat")
_PURPOSE = ContextVar("harness_operation_purpose", default=None)


def require_explicit_transport_allowed():
    execution = current_execution()
    if execution is not None and execution.harness is not None:
        execution.harness.failure = "unsupported_adapter"
        raise HarnessFailure("unsupported_adapter")


def require_failover_safe(error):
    execution = current_execution()
    if isinstance(error, HarnessFailure):
        raise error
    if execution is not None and execution.harness is not None and execution.harness.failure:
        raise HarnessFailure(execution.harness.failure) from None


@contextmanager
def use_kind(kind):
    token = _KIND.set(str(kind or "chat"))
    try:
        yield
    finally:
        _KIND.reset(token)


@contextmanager
def use_refinement_operation():
    """Один stable intent на задание, даже при смене continuation или исходников."""
    token = _PURPOSE.set("instruction_refinement")
    try:
        yield
    finally:
        _PURPOSE.reset(token)


def message_projection(response):
    message = response.choices[0].message
    calls = []
    for call in getattr(message, "tool_calls", None) or []:
        calls.append(
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
        )
    return TranscriptMessage(role="assistant", content=message.content, tool_calls=calls)


def cached_response(model, receipt):
    from service.infrastructure.harness.call_payload import receipt_finish_reason

    if not receipt.get("message"):
        raise HarnessFailure("provider_state_incompatible")
    message = {key: value for key, value in receipt["message"].items() if value is not None}
    return ChatCompletion.model_validate(
        {
            "id": "harness-cached",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": receipt_finish_reason(receipt),
                    "message": message,
                }
            ],
            "usage": {
                "prompt_tokens": receipt["prompt"],
                "completion_tokens": receipt["completion"],
                "total_tokens": receipt["prompt"] + receipt["completion"],
            },
        }
    )


async def paid_chat(call, *, provider, model, payload):
    execution = current_execution()
    client = execution.harness if execution is not None else None
    if client is None:
        return await call(), None
    intent = {"purpose": _PURPOSE.get()} if _PURPOSE.get() is not None else {}
    operation_id, cached = await client.before_call(
        provider, model, payload, kind=_KIND.get(), **intent
    )
    receipt_attempted = False
    try:
        if cached:
            restore_state(execution.provider_session, cached, provider=provider, model=model)
        result = cached_response(model, cached) if cached else await call()
        usage = result.usage.model_dump() if getattr(result, "usage", None) else {}
        if not cached:
            message = message_projection(result)
            receipt_attempted = True
            await client.complete_call(
                operation_id,
                usage=usage,
                message=message,
                finish_reason=result.choices[0].finish_reason,
                provider_state=capture_state(
                    execution.provider_session, provider=provider, model=model
                ),
            )
        receipt = execution.usage.record_usage(
            usage,
            provider=provider,
            model=model,
            kind=_KIND.get(),
            receipt_id=operation_id,
        )
        execution.register_response_receipt(result, receipt.receipt_id)
        if client.failure:
            raise HarnessFailure(client.failure)
        return result, operation_id
    except BaseException:
        if not cached and not receipt_attempted:
            await client.fail_call(operation_id)
        raise


async def dispatch_chat(module, call_args, call_kwargs, *, provider, model, execution):
    from .retry import retry_params, with_retry

    async def send():
        if execution is not None and execution.harness is not None:
            return await module.create_chat_completion(*call_args, **call_kwargs)
        return await with_retry(
            lambda: module.create_chat_completion(*call_args, **call_kwargs),
            label=f"chat:{provider}",
            **retry_params(),
        )

    messages = (
        call_kwargs.get("messages")
        if "messages" in call_kwargs
        else (call_args[0] if call_args else [])
    )
    return await paid_chat(
        send, provider=provider, model=model, payload={**call_kwargs, "messages": messages}
    )
