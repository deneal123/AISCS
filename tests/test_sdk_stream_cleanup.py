"""SDK interruption retains private output for accounting and closes transport."""

import asyncio
from types import SimpleNamespace

import pytest

from service.domain.client.calls import streaming
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat.provider_round import provider_events


class InterruptedStream:
    def __init__(self, failure, *, exact=False, close_failure=False, wait=False):
        self.failure = failure
        self.exact = exact
        self.close_failure = close_failure
        self.closed = 0
        self.wait = wait
        self.started = asyncio.Event()

    def __aiter__(self):
        async def iterate():
            delta = SimpleNamespace(
                content=None,
                reasoning="PRIVATE_REASONING " * 100,
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="private-call",
                        function=SimpleNamespace(name="lookup", arguments='{"query":"private"}'),
                    )
                ],
            )
            usage = (
                SimpleNamespace(prompt_tokens=13, completion_tokens=5, total_tokens=18)
                if self.exact
                else None
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=delta, finish_reason=None)], usage=usage
            )
            self.started.set()
            if self.wait:
                await asyncio.Event().wait()
            if self.failure is None:
                return
            raise self.failure("PRIVATE_PROVIDER_BODY")

        return iterate()

    async def close(self):
        self.closed += 1
        if self.close_failure:
            raise RuntimeError("PRIVATE_CLOSE_BODY")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("exact", [False, True])
@pytest.mark.parametrize("close_failure", [False, True])
async def test_sdk_interruption_closes_and_accounts_private_output(
    monkeypatch, caplog, failure, exact, close_failure
):
    transport = InterruptedStream(failure, exact=exact, close_failure=close_failure)

    async def create(**_kwargs):
        return transport

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(streaming, "_build_stream_payload", lambda **_kwargs: ({}, False))

    async def stream(*, messages, model, round_state, provider_session, **_kwargs):
        async for delta in streaming._stream_one_provider(
            client,
            "provider-a",
            messages,
            model,
            temperature=None,
            max_tokens=32,
            round_state=round_state,
            include_usage=False,
            provider_session=provider_session,
        ):
            yield delta

    with use_run_execution(PrivateRunResources()) as execution:
        events = []
        with pytest.raises(failure, match="PRIVATE_PROVIDER_BODY"):
            async for event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="answer-model",
                max_tokens=32,
                tools=None,
                pin_provider=None,
                tool_choice=None,
                provider_session=execution.provider_session,
            ):
                events.append(event)
        receipts = execution.usage.receipts
        assert len(receipts) == 1
        assert receipts[0].estimated is not exact
        assert receipts[0].completion == 5 if exact else receipts[0].completion > 0
        assert not execution.provider_session.has_active_round
        assert execution.provider_session.pinned_provider == "provider-a"
        assert events == []
    assert transport.closed == 1
    assert "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("exact", [False, True])
async def test_task_cancel_releases_sdk_stream_and_settles_accepted_receipt(monkeypatch, exact):
    transport = InterruptedStream(None, exact=exact, wait=True)

    async def create(**_kwargs):
        return transport

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(streaming, "_build_stream_payload", lambda **_kwargs: ({}, False))

    async def stream(*, messages, model, round_state, provider_session, **_kwargs):
        async for delta in streaming._stream_one_provider(
            client,
            "provider-a",
            messages,
            model,
            temperature=None,
            max_tokens=32,
            round_state=round_state,
            include_usage=False,
            provider_session=provider_session,
        ):
            yield delta

    with use_run_execution(PrivateRunResources()) as execution:

        async def consume():
            return [
                event
                async for event in provider_events(
                    stream,
                    messages=[{"role": "user", "content": "synthetic"}],
                    model="answer-model",
                    max_tokens=32,
                    tools=None,
                    pin_provider=None,
                    tool_choice=None,
                    provider_session=execution.provider_session,
                )
            ]

        task = asyncio.create_task(consume())
        await asyncio.wait_for(transport.started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.closed == 1
        assert len(execution.usage.receipts) == 1
        receipt = execution.usage.receipts[0]
        assert receipt.estimated is not exact
        assert receipt.completion == 5 if exact else receipt.completion > 0
        assert not execution.provider_session.has_active_round
