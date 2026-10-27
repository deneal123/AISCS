"""Acknowledged cancellation preserves committed model receipts without replay."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.billing.cancelled import (
    cancelled_result,
    restore_cancelled_checkpoint,
    settle_cancelled_execution,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal
from service.services.chat.infrastructure.chat_worker.execution.cancellation import CancelledByUser
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import MutableRunState


def recorded():
    attempt = str(uuid4())
    state = MutableRunState(execution_attempt_id=attempt, usage_checkpointed=True)
    state.usage_journal = UsageJournal.decode(
        {
            "schema_version": 1,
            "attempt_id": attempt,
            "revision": 1,
            "receipts": [
                {
                    "receipt_id": "accepted-call",
                    "provider": "gigachat",
                    "model": "GigaChat-2",
                    "kind": None,
                    "prompt": 200,
                    "completion": 100,
                    "estimated": False,
                }
            ],
        }
    )
    return state


@pytest.mark.asyncio
async def test_cancelled_accepted_call_returns_same_ledger_projection():
    state = recorded()

    async def stopped():
        raise CancelledByUser("run_cancelled")

    result = await settle_cancelled_execution(stopped(), state, "GigaChat-2")
    assert state.cancelled_execution is True
    assert result["total_tokens"] == 300
    assert result["per_call_usage"] == [state.usage_journal.receipts[0].payload()]
    assert result["metadata"] == {"execution_status": "partial"}
    assert "generated_files" not in result["metadata"]
    assert cancelled_result(state, "GigaChat-2") == result


@pytest.mark.parametrize("uncertain", ["unacknowledged", "different_attempt"])
def test_uncertain_checkpoint_cannot_authorize_settlement(uncertain):
    state = recorded()
    if uncertain == "unacknowledged":
        state.usage_checkpointed = False
    else:
        state.execution_attempt_id = str(uuid4())
    with pytest.raises(JobStateUnavailable):
        cancelled_result(state, "GigaChat-2")


@pytest.mark.asyncio
async def test_pre_acceptance_cancel_keeps_original_failure_path():
    async def stopped():
        raise CancelledByUser("run_cancelled")

    with pytest.raises(CancelledByUser):
        await settle_cancelled_execution(stopped(), MutableRunState(), "GigaChat-2")


@pytest.mark.asyncio
async def test_valid_terminal_wins_and_transport_failure_is_not_reinterpreted():
    async def completed():
        return {"reply": "accepted-terminal"}

    async def failed():
        raise RuntimeError("private-marker")

    assert await settle_cancelled_execution(completed(), recorded(), "GigaChat-2") == {
        "reply": "accepted-terminal"
    }
    with pytest.raises(RuntimeError):
        await settle_cancelled_execution(failed(), recorded(), "GigaChat-2")


@pytest.mark.asyncio
async def test_cancelled_journal_recovery_captures_once_without_model_work(monkeypatch):
    state = recorded()
    journal = state.usage_journal
    payload = {
        "_cancel_requested_v1": True,
        "_usage_journal_v1": journal.payload(),
        "_execution_attempt_v1": journal.attempt_id,
    }
    request = SimpleNamespace(
        job_id=str(uuid4()), user_id=str(uuid4()), selected_model="GigaChat-2"
    )
    capture = AsyncMock()
    repository = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={"payload": {"_prepared_turn_v1": {"safe": True}}}
        )
    )
    verified = SimpleNamespace(facts=SimpleNamespace(reservation_id=None, reserved_estimate=0))
    monkeypatch.setattr(
        "service.services.chat.infrastructure.chat_worker.billing.reservation.recovery.verify_accounting",
        AsyncMock(return_value=verified),
    )
    result = await restore_cancelled_checkpoint(
        SimpleNamespace(capture=capture),
        request=request,
        repository=repository,
        session=object(),
        state=MutableRunState(),
        payload=payload,
    )
    assert result == {"safe": True}
    capture.assert_awaited_once()
    call = capture.await_args.kwargs
    assert call["execution_result"]["total_tokens"] == 300
    assert call["file_url"] is None
    assert call["metadata"] == {"execution_status": "partial"}


@pytest.mark.asyncio
async def test_journal_without_owned_cancel_marker_does_not_finalize():
    capture = AsyncMock()
    result = await restore_cancelled_checkpoint(
        SimpleNamespace(capture=capture),
        request=None,
        repository=None,
        session=None,
        state=MutableRunState(),
        payload={"_usage_journal_v1": recorded().usage_journal.payload()},
    )
    assert result is None
    capture.assert_not_awaited()
