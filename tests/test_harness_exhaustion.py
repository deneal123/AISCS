"""Исчерпание retry не создаёт расходы, доказательства или повторные действия."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.interrupted import (
    finish_exhausted_delivery,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import exhaustion
from service.services.chat.infrastructure.chat_worker.harness.cancelled_usage import canonical_usage
from service.shared.task_contract import TaskResultV2


def payload():
    attempt = str(uuid4())
    return {
        "_harness_task_v1": str(uuid4()),
        "_execution_attempt_v1": attempt,
        "_harness_transport_retry_v1": {"attempt_id": attempt, "count": 3, "state": "blocked"},
    }


@pytest.fixture
def known_task(monkeypatch):
    saved = payload()
    task_id, attempt = saved["_harness_task_v1"], saved["_execution_attempt_v1"]
    request = SimpleNamespace(
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
        selected_model="test-model",
    )
    row = {"task_id": UUID(task_id), "job_payload": saved, "fencing_epoch": 4}
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        ),
    )
    grant = {
        "operation_id": uuid4(),
        "state": "succeeded",
        "request": {"provider": "gigachat", "model": "test-model", "kind": "chat"},
        "receipt": {"prompt": 7, "completion": 2, "estimated": False},
    }
    monkeypatch.setattr(
        exhaustion,
        "verify_accounting",
        AsyncMock(
            return_value=SimpleNamespace(
                facts=SimpleNamespace(
                    attempt_id=attempt, reservation_id=str(uuid4()), reserved_estimate=100
                )
            )
        ),
    )
    monkeypatch.setattr(exhaustion, "reconcile_tool_fees", AsyncMock())
    monkeypatch.setattr(exhaustion, "grant_rows", AsyncMock(return_value=[grant]))
    monkeypatch.setattr(exhaustion, "snapshot", AsyncMock(return_value=object()))
    projection = {
        "schema_version": 2,
        "status": "blocked",
        "verified": False,
        "blocker": "checkpoint_unavailable",
        "confirmed": [],
        "unchecked": ["verify_project"],
        "references": [],
        "rounds": 5,
        "repair_cycles": 1,
    }
    monkeypatch.setattr(exhaustion, "read_result", AsyncMock(return_value=projection))
    stage = AsyncMock()
    monkeypatch.setattr(exhaustion, "stage_usage_journal", stage)
    capture = AsyncMock()
    repository = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={"payload": {"_prepared_turn_v1": {"fixture": "checkpoint"}}}
        )
    )
    return SimpleNamespace(
        saved=saved,
        request=request,
        session=session,
        grant=grant,
        projection=projection,
        stage=stage,
        capture=capture,
        repository=repository,
        state=SimpleNamespace(),
        row=row,
    )


async def restore_fixture(task):
    return await exhaustion.restore_exhausted_checkpoint(
        SimpleNamespace(capture=task.capture),
        request=task.request,
        repository=task.repository,
        session=task.session,
        state=task.state,
        payload=task.saved,
    )


@pytest.mark.asyncio
async def test_confirmed_cost_enters_existing_checkpoint_with_original_receipt_ids(known_task):
    task = known_task
    assert await restore_fixture(task) == {"fixture": "checkpoint"}
    task.stage.assert_awaited_once()
    task.capture.assert_awaited_once()
    saved = task.stage.call_args.kwargs["payload"]
    assert saved["receipts"][0]["receipt_id"] == str(task.grant["operation_id"])
    assert saved["attempt_id"] == task.saved["_execution_attempt_v1"]
    assert task.state.harness_epoch == 4
    assert task.capture.call_args.kwargs["metadata"]["task_result"] == task.projection
    sql = str(task.session.execute.call_args_list[0].args[0])
    assert "FOR UPDATE OF t,j" in sql and "execution_attempt_id=:attempt" in sql
    assert "_cancel_requested_v1" in sql and "profile.chat_threads" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", ["cost_unknown", "operation_unknown"])
async def test_uncertainty_never_captures_terminal_or_releases_a_hold(known_task, unknown):
    task = known_task
    if unknown == "cost_unknown":
        task.grant["state"] = "unknown"
    else:
        task.projection["blocker"] = unknown
    with pytest.raises(JobStateUnavailable):
        await restore_fixture(task)
    task.stage.assert_not_awaited()
    task.capture.assert_not_awaited()
    assert not hasattr(task.state, "usage_journal")


@pytest.mark.asyncio
async def test_ownership_is_rechecked_before_accounting_or_capture(known_task, monkeypatch):
    task = known_task
    task.row["job_payload"] = {**task.saved, "_cancel_requested_v1": True}
    verify = AsyncMock()
    monkeypatch.setattr(exhaustion, "verify_accounting", verify)
    with pytest.raises(JobStateUnavailable):
        await restore_fixture(task)
    verify.assert_not_awaited()
    task.capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhaustion_before_any_paid_dispatch_closes_without_fictitious_receipts(
    known_task, monkeypatch
):
    task = known_task
    task.row.update(admission={"schema_version": 1}, usage_history=[], settled_credits=0)
    monkeypatch.setattr(exhaustion, "grant_rows", AsyncMock(return_value=[]))
    monkeypatch.setattr(exhaustion, "snapshot", AsyncMock(return_value=SimpleNamespace(state=None)))
    monkeypatch.setattr(exhaustion, "read_result", AsyncMock(return_value=None))
    assert await restore_fixture(task) == {"fixture": "checkpoint"}
    task.stage.assert_not_awaited()
    assert task.state.usage_journal is None
    captured = task.capture.call_args.kwargs["execution_result"]
    assert captured["total_tokens"] == 0 and captured["per_call_usage"] == []
    result = captured["metadata"]["task_result"]
    assert result["status"] == "blocked" and result["unchecked"] == ["contract"]
    assert result["confirmed"] == result["references"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_proof", ["admission", "history", "settled"])
async def test_no_current_receipts_is_not_itself_a_proof_of_zero_cost(
    known_task, monkeypatch, missing_proof
):
    task = known_task
    task.row.update(admission={"schema_version": 1}, usage_history=[], settled_credits=0)
    if missing_proof == "admission":
        task.row["admission"] = None
    elif missing_proof == "history":
        task.row["usage_history"] = [{"receipts": []}]
    else:
        task.row["settled_credits"] = 1
    monkeypatch.setattr(exhaustion, "grant_rows", AsyncMock(return_value=[]))
    with pytest.raises(JobStateUnavailable):
        await restore_fixture(task)
    task.capture.assert_not_awaited()


@pytest.mark.parametrize("count", [None, True, 0, 1, 2, 4, "3", 3.0])
def test_exhausted_requires_the_last_durable_counter(count):
    saved = payload()
    saved["_harness_transport_retry_v1"]["count"] = count
    assert not exhaustion.exhausted(saved)


def test_cancelled_pending_or_old_attempt_cannot_become_exhausted():
    saved = payload()
    assert exhaustion.exhausted(saved)
    saved["_cancel_requested_v1"] = True
    assert not exhaustion.exhausted(saved)
    saved.pop("_cancel_requested_v1")
    saved["_harness_transport_retry_v1"]["state"] = "pending"
    assert not exhaustion.exhausted(saved)
    saved["_harness_transport_retry_v1"]["state"] = "blocked"
    saved["_execution_attempt_v1"] = str(uuid4())
    assert not exhaustion.exhausted(saved)


def test_blocked_result_preserves_receipt_identity_and_confirmed_work():
    grant_id = uuid4()
    journal = canonical_usage(
        str(uuid4()),
        None,
        [
            {
                "operation_id": grant_id,
                "state": "succeeded",
                "request": {"provider": "gigachat", "model": "test-model", "kind": "chat"},
                "receipt": {"prompt": 7, "completion": 2, "estimated": False},
            }
        ],
    )
    task = TaskResultV2(
        schema_version=2,
        status="blocked",
        verified=False,
        blocker="checkpoint_unavailable",
        confirmed=["script"],
        unchecked=["verify_project"],
        references=[
            {
                "criterion_id": "script",
                "operation_id": str(uuid4()),
                "kind": "file",
                "target": "hello_world.py",
                "digest": "a" * 64,
                "source_revision": "r1",
            }
        ],
        rounds=5,
        repair_cycles=1,
    )
    result = exhaustion.exhausted_result(journal, task, "test-model")
    assert result["total_tokens"] == 9
    assert result["per_call_usage"][0]["receipt_id"] == str(grant_id)
    assert result["metadata"]["task_result"] == task.model_dump(mode="json")
    assert "cancel" not in result["metadata"]


@pytest.mark.asyncio
async def test_pending_retry_does_not_restore_or_finalize():
    restore, finalize = AsyncMock(), AsyncMock()
    result = {"status": "recovery_pending", "recovery_retry_count": 3}
    assert (
        await finish_exhausted_delivery(
            result,
            request=None,
            state=None,
            hooks=SimpleNamespace(prepared_results=SimpleNamespace(restore=restore)),
            finalize=finalize,
            services={},
        )
        == result
    )
    restore.assert_not_awaited()
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_exhaustion_uses_existing_prepared_finalization_without_another_dispatch():
    saved = {
        "usage": {"total_tokens": 9},
        "reply": "Сохранено",
        "metadata": {"task_result": {}},
        "resolved_model": "test-model",
    }
    state = SimpleNamespace(restored_result=saved)
    restore, finalize = AsyncMock(return_value=True), AsyncMock(return_value={"status": "success"})
    hooks = SimpleNamespace(
        prepared_results=SimpleNamespace(restore=restore), record_catalog_events=None
    )
    services = {
        "job_repo": object(),
        "session": object(),
        "file_service": object(),
        "redis_client": object(),
    }
    request = object()
    result = await finish_exhausted_delivery(
        {"status": "error", "recovery_retry_count": 3},
        request=request,
        state=state,
        hooks=hooks,
        finalize=finalize,
        services=services,
    )
    assert result == {"status": "success"}
    restore.assert_awaited_once()
    execution = {
        **saved["usage"],
        **{key: saved[key] for key in ("reply", "metadata", "resolved_model")},
    }
    finalize.assert_awaited_once_with(
        request, execution, None, state=state, hooks=hooks, **services
    )


@pytest.mark.asyncio
async def test_unknown_cost_keeps_blocked_evidence_without_finalization(monkeypatch):
    from service.services.chat.infrastructure.chat_worker.execution import interrupted

    abort = AsyncMock(return_value={"status": "error"})
    monkeypatch.setattr(interrupted, "abort_unverified_job", abort)
    restore = AsyncMock(side_effect=JobStateUnavailable("private"))
    finalize = AsyncMock()
    result = {
        "status": "error",
        "recovery_retry_count": 3,
        "metadata": {"task_result": {"status": "blocked", "blocker": "cost_unknown"}},
    }
    actual = await finish_exhausted_delivery(
        result,
        request=SimpleNamespace(job_id=str(uuid4())),
        state=object(),
        hooks=SimpleNamespace(
            prepared_results=SimpleNamespace(restore=restore), record_catalog_events=None
        ),
        finalize=finalize,
        services={
            "session": object(),
            "publisher": object(),
            "job_repo": object(),
            "file_service": object(),
            "redis_client": object(),
        },
    )
    assert actual["metadata"] == result["metadata"]
    assert "private" not in str(actual)
    finalize.assert_not_awaited()
