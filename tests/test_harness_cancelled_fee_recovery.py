"""Stop сверяет потерянный ACK надбавки по прежнему доверенному receipt инструмента."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4, uuid5

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import cancelled_usage
from service.shared.harness_protocol import EffectIntent, EffectResult, PaidCall
from service.shared.task_contract import digest_payload


@pytest.fixture
def stopped_task(monkeypatch):
    task, owner, thread, attempt = (uuid4() for _ in range(4))
    effect = EffectIntent(
        operation_id=str(uuid4()),
        name="ide_write_file",
        action="write",
        arguments='{"path":"hello_world.py"}',
        source_revision="r1",
    )
    call = PaidCall(
        operation_id=str(uuid5(UUID(effect.operation_id), "billing")),
        provider="local",
        model="workspace_tool",
        prompt=0,
        completion=0,
        request_digest=digest_payload(effect.model_dump(mode="json")),
        kind="tool",
        billing_tool="workspace_tool",
    )
    fee = {
        "operation_id": UUID(call.operation_id),
        "request": call.model_dump(mode="json"),
        "state": "unknown",
        "receipt": None,
    }
    proof = {
        "operation_id": fee["operation_id"],
        "request": fee["request"],
        "intent": effect.model_dump(mode="json"),
        "receipt": EffectResult(
            operation_id=effect.operation_id,
            status="succeeded",
            text="PRIVATE_DIAGNOSTIC",
            charged=True,
        ).model_dump(mode="json"),
    }
    model = {
        "operation_id": uuid4(),
        "state": "succeeded",
        "request": {"provider": "gigachat", "model": "test-model", "kind": "chat"},
        "receipt": {"prompt": 7, "completion": 3, "estimated": False},
    }
    row = {"task_id": task, "admission": {}, "usage_history": [], "settled_credits": 0}
    calls = []

    async def execute(sql, params):
        query = str(sql)
        calls.append((query, params))
        if "SELECT t.task_id" in query:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        if "JOIN profile.harness_operation" in query:
            rows = [proof] if fee["state"] in {"dispatched", "unknown"} else []
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        if "SET state=:state" in query:
            fee["state"] = params["state"]
        return None

    session = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock())
    monkeypatch.setattr(
        cancelled_usage, "grant_rows", AsyncMock(side_effect=lambda *_: deepcopy([model, fee]))
    )
    stage = AsyncMock()
    monkeypatch.setattr(cancelled_usage, "stage_usage_journal", stage)
    request = SimpleNamespace(job_id=str(task), user_id=str(owner), thread_id=str(thread))
    payload = {
        "_harness_task_v1": str(task),
        "_execution_attempt_v1": str(attempt),
        "_cancel_requested_v1": True,
    }
    return session, request, payload, fee, proof, model, calls, stage


@pytest.mark.asyncio
@pytest.mark.parametrize("charged", [True, False])
async def test_stop_reconciles_committed_effect_before_restoring_usage(stopped_task, charged):
    db, request, payload, fee, proof, model, calls, stage = stopped_task
    proof["receipt"]["charged"] = charged
    await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert fee["state"] == ("succeeded" if charged else "waived")
    journal = deepcopy(payload["_usage_journal_v1"])
    assert journal["receipts"][0]["receipt_id"] == str(model["operation_id"])
    assert len(journal["receipts"]) == 1
    assert journal["receipts"][0]["prompt"] == 7
    await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert payload["_usage_journal_v1"] == journal
    assert sum("SET state=:state" in query for query, _ in calls) == 1
    assert stage.await_count == 2
    assert not any("INSERT" in query or "state='dispatched'" in query for query, _ in calls)
    assert "PRIVATE_DIAGNOSTIC" not in str(stage.await_args_list)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_effect_without_charge_proof_remains_unknown(stopped_task):
    db, request, payload, fee, proof, _, _, stage = stopped_task
    proof["receipt"].pop("charged")
    with pytest.raises(JobStateUnavailable, match="cost unknown"):
        await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert fee["state"] == "unknown"
    assert "_usage_journal_v1" not in payload
    stage.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_attempt_cannot_reconcile_or_waive_grants(stopped_task):
    db, request, payload, fee, _, _, _, stage = stopped_task
    db.execute.side_effect = None
    db.execute.return_value = SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: None))
    with pytest.raises(JobStateUnavailable, match="ownership unavailable"):
        await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert db.execute.await_count == 1
    assert fee["state"] == "unknown"
    stage.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_model_spend_survives_confirmed_local_effect(stopped_task):
    db, request, payload, fee, _, model, _, stage = stopped_task
    model["state"] = "unknown"
    with pytest.raises(JobStateUnavailable, match="cost unknown"):
        await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert fee["state"] == "succeeded"
    assert "_usage_journal_v1" not in payload
    stage.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciliation_failure_does_not_waive_or_checkpoint(stopped_task, monkeypatch):
    db, request, payload, fee, _, _, calls, stage = stopped_task
    reconcile = AsyncMock(side_effect=JobStateUnavailable("receipt unavailable"))
    monkeypatch.setattr(cancelled_usage, "reconcile_tool_fees", reconcile)
    with pytest.raises(JobStateUnavailable, match="receipt unavailable"):
        await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    assert len(calls) == 1 and "FOR UPDATE OF t,j" in calls[0][0]
    assert fee["state"] == "unknown"
    assert "_usage_journal_v1" not in payload
    stage.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["_cancel_requested_v1", "_harness_task_v1"])
async def test_only_stopped_harness_can_use_cancel_reconciliation(stopped_task, missing):
    db, request, payload, fee, _, _, _, stage = stopped_task
    payload.pop(missing)
    await cancelled_usage.restore_cancelled_usage(None, db, request, payload)
    db.execute.assert_not_awaited()
    stage.assert_not_awaited()
    assert fee["state"] == "unknown"
