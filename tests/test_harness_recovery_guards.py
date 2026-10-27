"""Offline fencing/Stop/unknown-ACK transaction-body checks for worker recovery."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import recovery as harness_recovery
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


@pytest.fixture
def recovery(monkeypatch):
    monkeypatch.setattr(harness_recovery, "reconcile_tool_fees", AsyncMock(return_value=0))
    monkeypatch.setattr(
        harness_recovery, "settings", lambda: SimpleNamespace(ide_enabled=True, pdf_enabled=False)
    )
    job, user, thread, old_attempt, reservation = (uuid4() for _ in range(5))
    request = WorkerRunRequest(
        job_id=str(job), thread_id=str(thread), text="task", user_id=str(user)
    )
    usage = {"revision": 12, "receipts": [{"id": "prior"}]}
    row = dict(
        task_id=job,
        active_job_id=job,
        execution_attempt_id=old_attempt,
        fencing_epoch=3,
        settled_credits=50,
        admission={"credit_limit": 200},
        usage_history=[],
        job_status="PROCESSING",
        job_payload={
            "thread_id": str(thread),
            "_execution_attempt_v1": str(old_attempt),
            "_execution_accounting_v1": {
                "attempt_id": str(old_attempt),
                "reservation_id": str(reservation),
                "reserved_estimate": 200,
            },
            "_usage_journal_v1": usage,
        },
    )
    calls = []

    async def execute(sql, params):
        calls.append((str(sql), params))
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))

    db = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock())
    return request, row, db, calls


@pytest.mark.asyncio
async def test_recovery_changes_owner_without_resetting_budget_or_discarding_usage(recovery):
    request, row, db, calls = recovery
    state = MutableRunState()
    assert await harness_recovery.recover_harness(db, request, state)
    assert state.harness_task_id == request.job_id and state.harness_epoch == 4
    assert state.execution_attempt_id != str(row["execution_attempt_id"])
    assert state.reservation_id == row["job_payload"]["_execution_accounting_v1"]["reservation_id"]
    assert state.reserved_estimate == 200 and state.harness_remaining == 150
    payload = json.loads(calls[1][1]["body"])
    assert "_usage_journal_v1" not in payload
    assert payload["_execution_accounting_v1"]["attempt_id"] == state.execution_attempt_id
    history = json.loads(calls[2][1]["history"])
    assert history == [row["job_payload"]["_usage_journal_v1"]]
    assert "state='unknown'" in calls[3][0] and "state='dispatched'" in calls[3][0]
    assert not any("checkpoint=" in sql or "DELETE" in sql for sql, _ in calls)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latch",
    ["_cancel_requested_v1", "_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"],
)
async def test_stopped_or_latched_job_cannot_transfer_to_another_execution(recovery, latch):
    request, row, db, calls = recovery
    row["job_payload"][latch] = True
    with pytest.raises(JobStateUnavailable):
        await harness_recovery.recover_harness(db, request, MutableRunState())
    assert len(calls) == 1
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_transfer_commit_ack_never_admits_execution(recovery):
    request, _, db, _ = recovery
    db.commit.side_effect = ConnectionError("PRIVATE_DB_DIAGNOSTIC")
    with pytest.raises(JobStateUnavailable, match="Harness recovery unavailable") as error:
        await harness_recovery.recover_harness(db, request, MutableRunState())
    assert "PRIVATE_DB_DIAGNOSTIC" not in str(error.value)


@pytest.mark.asyncio
async def test_finalization_of_old_attempt_is_rejected(recovery):
    request, row, _, _ = recovery
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))
    state = MutableRunState(
        harness_task_id=str(row["task_id"]),
        execution_attempt_id=str(row["execution_attempt_id"]),
        harness_epoch=row["fencing_epoch"],
    )
    with pytest.raises(JobStateUnavailable, match="Harness execution fenced"):
        await harness_recovery.verify_harness_attempt(db, request, state)
    query = db.scalar.call_args.args[0]
    assert "fencing_epoch=:epoch" in str(query) and "FOR UPDATE OF t,j" in str(query)
