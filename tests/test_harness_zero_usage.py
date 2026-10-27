"""Отмена без dispatch не создаёт фиктивных usage receipts или подтверждений."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.billing.cancelled import cancelled_result
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import cancellation
from service.services.chat.infrastructure.chat_worker.harness.zero_usage import (
    verified_without_dispatch,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import MutableRunState


def proof(**changes):
    row = {"admission": {"schema_version": 1}, "usage_history": [], "settled_credits": 0}
    row.update(changes)
    return row


def test_zero_requires_no_paid_dispatch_in_any_attempt():
    assert verified_without_dispatch(proof(), {}, []) is True
    assert verified_without_dispatch(proof(), {}, [{"state": "waived"}]) is True
    state = MutableRunState(
        cancelled_execution=True,
        cancelled_without_dispatch=True,
        usage_checkpointed=True,
        execution_attempt_id=str(uuid4()),
    )
    result = cancelled_result(state, "GigaChat-2-Max")
    assert result["total_tokens"] == 0 and result["per_call_usage"] == []
    assert state.usage_journal is None


@pytest.mark.parametrize("state", ["allocated", "dispatched", "unknown", "succeeded"])
def test_grants_without_proof_of_non_dispatch_block_zero(state):
    with pytest.raises(JobStateUnavailable):
        verified_without_dispatch(proof(), {}, [{"state": state}])


@pytest.mark.parametrize(
    "changes,payload",
    [
        ({"admission": None}, {}),
        ({"usage_history": [{"receipts": []}]}, {}),
        ({"settled_credits": 1}, {}),
        ({}, {"_usage_journal_v1": {"receipts": []}}),
    ],
)
def test_absent_current_journal_does_not_prove_zero(changes, payload):
    with pytest.raises(JobStateUnavailable):
        verified_without_dispatch(proof(**changes), payload, [])


def test_zero_marker_without_backend_cancellation_cannot_finalize():
    with pytest.raises(JobStateUnavailable):
        cancelled_result(MutableRunState(cancelled_without_dispatch=True), None)


@pytest.mark.asyncio
async def test_stop_before_contract_reports_unchecked_contract_without_invented_evidence(
    monkeypatch,
):
    request = SimpleNamespace(job_id=str(uuid4()), user_id=str(uuid4()), thread_id=str(uuid4()))
    state = MutableRunState(
        harness_task_id=request.job_id,
        execution_attempt_id=str(uuid4()),
        cancelled_execution=True,
    )
    row = {"task_id": request.job_id}
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        )
    )
    monkeypatch.setattr(
        cancellation, "snapshot", AsyncMock(return_value=SimpleNamespace(state=None))
    )
    monkeypatch.setattr(cancellation, "read_result", AsyncMock(return_value=None))
    result = await cancellation.cancelled_projection(session, request, state)
    assert result["status"] == "cancelled" and result["verified"] is False
    assert result["unchecked"] == ["contract"]
    assert result["confirmed"] == result["references"] == []


@pytest.mark.asyncio
async def test_zero_recovery_requires_owned_database_lock_and_creates_no_journal(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.harness import cancelled_usage

    request = SimpleNamespace(job_id=str(uuid4()), user_id=str(uuid4()), thread_id=str(uuid4()))
    payload = {
        "_cancel_requested_v1": True,
        "_harness_task_v1": request.job_id,
        "_execution_attempt_v1": str(uuid4()),
    }
    row = {**proof(), "task_id": uuid4()}
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        )
    )
    monkeypatch.setattr(cancelled_usage, "grant_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(cancelled_usage, "reconcile_tool_fees", AsyncMock(return_value=0))
    stage = AsyncMock()
    monkeypatch.setattr(cancelled_usage, "stage_usage_journal", stage)
    assert await cancelled_usage.restore_cancelled_usage(None, session, request, payload) is True
    query, parameters = session.execute.await_args_list[0].args
    assert "FOR UPDATE OF t,j" in str(query)
    assert "j.payload->>'_cancel_requested_v1'='true'" in str(query)
    assert "t.execution_attempt_id=:attempt" in str(query)
    assert str(parameters["attempt"]) == payload["_execution_attempt_v1"]
    assert "_usage_journal_v1" not in payload
    stage.assert_not_awaited()
