"""Acceptance, not prior pinning, owns interrupted-round billing."""

import asyncio
from collections.abc import AsyncGenerator

import pytest

from service.domain.client.protocol import PinSource
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat.provider_round import provider_events


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_unaccepted_pinned_continuation_does_not_create_receipt(failure):
    async def stream(**_kwargs) -> AsyncGenerator[str]:
        raise failure("PRIVATE_PROVIDER_BODY")
        yield ""  # pragma: no cover

    with use_run_execution(PrivateRunResources()) as execution:
        session = execution.provider_session
        session.complete_round(
            provider="provider-a",
            model="answer-model",
            usage={"prompt": 13, "completion": 5, "total": 18},
            call_id="previous-call",
        )
        before = execution.usage.receipts
        with pytest.raises(failure):
            async for _event in provider_events(
                stream,
                messages=[{"role": "user", "content": "synthetic"}],
                model="answer-model",
                max_tokens=32,
                tools=None,
                pin_provider="provider-a",
                tool_choice=None,
                provider_session=session,
            ):
                pass
        assert execution.usage.receipts == before
        assert session.round_count == 1
        assert session.pinned_provider == "provider-a"
        assert not session.has_active_round


@pytest.mark.asyncio
@pytest.mark.parametrize("exact", [False, True])
async def test_accepted_cancellation_settles_same_receipt(exact):
    async def stream(*, provider_session, round_state, model, **_kwargs):
        provider_session.accept_round(
            provider="provider-a",
            model=model,
            source=PinSource.STREAM_DELTA,
            call_id="accepted-call",
        )
        if exact:
            round_state.update({"prompt": 13, "completion": 5, "total": 18})
        yield "accepted partial response"
        raise asyncio.CancelledError("PRIVATE_PROVIDER_BODY")

    with use_run_execution(PrivateRunResources()) as execution:
        with pytest.raises(asyncio.CancelledError):
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
        assert receipts[0].estimated is not exact
        assert receipts[0].total == 18 if exact else receipts[0].total > 0
        assert not execution.provider_session.has_active_round
        assert execution.provider_session.pinned_provider == "provider-a"
