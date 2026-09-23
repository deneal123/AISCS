"""S30 regressions for the single run owner and ledger-native provider rounds."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest

from service.domain.client.protocol import PinSource, ProviderRoundState
from service.domain.run_context import (
    PrivateRunResources,
    RunExecutionContextError,
    current_execution,
    require_current_execution,
    use_run_execution,
)
from service.domain.runners.chat_provider_round import provider_events
from service.domain.usage_ledger import UsageKind, UsageLedger


def test_missing_context_is_bounded_and_never_constructed_implicitly() -> None:
    import service.domain.run_context as run_context

    token = run_context._CURRENT.set(None)
    try:
        with pytest.raises(RunExecutionContextError) as caught:
            require_current_execution()
    finally:
        run_context._CURRENT.reset(token)

    assert caught.value.code == "missing_context"
    assert str(caught.value) == "missing_context"


def test_usage_scope_filters_kind_and_is_read_only() -> None:
    ledger = UsageLedger()
    scope = ledger.open_scope(kind=UsageKind.TOOL_SELECTOR)
    ledger.record_usage(
        {"prompt": 7, "completion": 2},
        provider="provider-a",
        model="selector-model",
        kind=UsageKind.TOOL_SELECTOR,
        receipt_id="selector-call",
    )
    ledger.record_usage(
        {"prompt": 11, "completion": 3},
        provider="provider-a",
        model="answer-model",
        kind=UsageKind.CHAT,
        receipt_id="chat-call",
    )

    first = ledger.project_scope(scope)
    replay = ledger.project_scope(scope)

    assert first == replay
    assert first["total"] == 9
    assert [item["receipt_id"] for item in first["calls"]] == ["selector-call"]
    assert len(ledger.receipts) == 2


@pytest.mark.asyncio
async def test_exact_usage_before_stream_failure_keeps_one_exact_receipt() -> None:
    async def stream(
        *,
        provider_session,
        round_state: ProviderRoundState,
        model: str,
        **_kwargs,
    ) -> AsyncGenerator[str]:
        provider_session.accept_round(
            provider="provider-a",
            model=model,
            source=PinSource.STREAM_DELTA,
            call_id="accepted-call",
        )
        round_state.update(
            {
                "provider": "provider-a",
                "model": model,
                "prompt": 13,
                "completion": 5,
                "total": 18,
            }
        )
        yield "accepted"
        raise RuntimeError("PRIVATE_PROVIDER_BODY")

    with use_run_execution(PrivateRunResources()) as execution:
        with pytest.raises(RuntimeError):
            async for _event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="answer-model",
                max_tokens=32,
                tools=None,
                pin_provider=None,
                tool_choice=None,
                provider_session=execution.provider_session,
            ):
                pass

        receipts = execution.usage.receipts

    assert len(receipts) == 1
    assert receipts[0].receipt_id == "accepted-call"
    assert receipts[0].total == 18
    assert receipts[0].estimated is False


@pytest.mark.asyncio
async def test_failure_before_acceptance_creates_no_receipt_or_pinning() -> None:
    async def stream(**_kwargs) -> AsyncGenerator[str]:
        if _kwargs.get("unexpected_yield"):  # pragma: no cover
            yield ""
        raise RuntimeError("PRIVATE_PROVIDER_BODY")

    with use_run_execution(PrivateRunResources()) as execution:
        with pytest.raises(RuntimeError):
            async for _event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="answer-model",
                max_tokens=32,
                tools=None,
                pin_provider=None,
                tool_choice=None,
                provider_session=execution.provider_session,
            ):
                pass

        assert execution.usage.receipts == ()
        assert execution.provider_session.pinned_provider is None


def test_failed_provider_attempt_state_is_cleared_before_failover() -> None:
    state = ProviderRoundState()
    state.update(
        {
            "provider": "provider-a",
            "model": "model-a",
            "prompt": 100,
            "completion": 20,
            "tool_calls": [{"name": "private-tool"}],
            "reasoning": "private reasoning",
        }
    )

    state.reset_attempt(provider="provider-b", model="model-b")

    assert state.provider == "provider-b"
    assert state.model == "model-b"
    assert state.prompt == 0
    assert state.completion == 0
    assert state.tool_calls == []
    assert state.reasoning == ""


@pytest.mark.asyncio
async def test_legacy_stream_adapter_opens_one_scoped_run(monkeypatch) -> None:
    import service.domain.client.calls.legacy_stream as legacy_stream
    import service.domain.run_context as run_context

    observed = {}

    async def typed_stream(_messages, _model, *, round_state, provider_session, **_kwargs):
        observed["execution"] = current_execution()
        observed["session"] = provider_session
        round_state.update(
            {
                "provider": "provider-a",
                "model": "model-a",
                "prompt": 3,
                "completion": 1,
            }
        )
        yield "ok"

    monkeypatch.setattr(legacy_stream, "stream_provider_completion", typed_stream)
    projection = {}
    token = run_context._CURRENT.set(None)
    try:
        chunks = [
            chunk
            async for chunk in legacy_stream.stream_chat_completion(
                [],
                "model-a",
                usage_out=projection,
            )
        ]
        assert current_execution() is None
    finally:
        run_context._CURRENT.reset(token)

    assert chunks == ["ok"]
    assert observed["execution"] is not None
    assert observed["session"] is observed["execution"].provider_session
    assert projection["total"] == 4


@pytest.mark.asyncio
async def test_legacy_stream_adapter_reuses_caller_round_state(monkeypatch) -> None:
    import service.domain.client.calls.legacy_stream as legacy_stream
    from service.domain.client.protocol import ProviderRoundState

    observed = {}

    async def typed_stream(_messages, _model, *, round_state, **_kwargs):
        observed["round_state"] = round_state
        yield "ok"

    monkeypatch.setattr(legacy_stream, "stream_provider_completion", typed_stream)
    supplied = ProviderRoundState()

    chunks = [
        chunk
        async for chunk in legacy_stream.stream_chat_completion(
            [],
            "model-a",
            round_state=supplied,
        )
    ]

    assert chunks == ["ok"]
    assert observed["round_state"] is supplied
