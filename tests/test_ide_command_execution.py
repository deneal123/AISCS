"""Offline orchestration regressions, deliberately not a live exec acceptance."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.application.ide.commands import service as execution
from service.services.chat.persistence.harness.commands import recipes
from service.services.chat.persistence.harness.commands import repository as journal
from service.shared.harness_protocol import HarnessFailure
from tests.test_ide_harness_commands import command, result, running
from tests.test_task_contract import state


def subject(record, *, stopped=False):
    service = execution.AgentConsole(
        None, None, SimpleNamespace(redis_client=None, pg_connector=None)
    )
    service.repo = SimpleNamespace(
        command_status=AsyncMock(return_value=record),
        exchange=AsyncMock(
            return_value={
                "snapshot": {
                    "stopped": stopped,
                    "state": {"contract": {"criteria": []}},
                }
            }
        ),
        transition=AsyncMock(
            side_effect=lambda *args, **kw: record.advance(
                **{key: val for key, val in kw.items() if key != "files"}
            )
        ),
    )
    service.binding = AsyncMock(return_value=SimpleNamespace(workspace_id=record.workspace_id))
    service.request = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_completed_process_without_output_retires_gate_but_never_verifies():
    record = running()
    service = subject(record)
    service.request.return_value = {
        "running": False,
        "cleanup_confirmed": True,
        "receipt": None,
        "final_revision": "final",
        "files": {},
    }
    actual = await service.status(
        SimpleNamespace(thread_id="thread"), record.operation_id, "private"
    )
    assert actual["state"] == "failed" and actual["blocker"] == "output_unavailable"
    assert actual["verification"]["status"] == "blocked"
    assert service.repo.transition.await_args.kwargs["cleanup_confirmed"]


@pytest.mark.asyncio
async def test_missing_final_revision_never_reuses_precommand_verification():
    record = running()
    service = subject(record)
    service.request.return_value = {
        "running": False,
        "cleanup_confirmed": True,
        "receipt": {"result": result()},
        "final_revision": None,
    }
    actual = await service.status(
        SimpleNamespace(thread_id="thread"), record.operation_id, "private"
    )
    assert actual["state"] == "failed" and actual["blocker"] == "source_revision_unavailable"
    assert actual["verification"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_unknown_cleanup_keeps_command_and_pin_unresolved():
    record = running()
    service = subject(record)
    service.request.return_value = {"running": False, "cleanup_confirmed": False}
    actual = await service.status(object(), record.operation_id, "private")
    assert actual["state"] == "unknown"
    assert "cleanup_confirmed" not in service.repo.transition.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stopped,deadline,expected", [(True, None, "cancelled"), (False, 1, "failed")]
)
async def test_stop_and_deadline_are_distinct_and_address_same_process(stopped, deadline, expected):
    record = running(
        deadline_at=deadline,
        supervisor={"pid": 123, "start_time": "42", "version": 1},
    )
    service = subject(record, stopped=stopped)
    service.request.return_value = {
        "running": False,
        "cleanup_confirmed": True,
        "receipt": {"result": result(exit_code=-15), "cancelled": True},
        "final_revision": "final",
    }
    actual = await service.status(
        SimpleNamespace(thread_id="thread"), record.operation_id, "private"
    )
    assert actual["state"] == expected
    assert service.request.await_args.args[3] == "stop"
    if deadline:
        assert actual["blocker"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_repeated_run_only_observes_same_operation():
    record = running(deadline_at=time.time() + 60)
    service = subject(record)
    service.repo.admit_command = AsyncMock(return_value=record)
    service.status = AsyncMock(return_value={"state": "running"})
    assert await service.run(object(), record.operation_id, record.spec, "private") == {
        "state": "running"
    }
    service.status.assert_awaited_once()
    service.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_snapshot_failure_never_creates_an_exec(monkeypatch):
    record = command()
    service = subject(record)
    service.repo.admit_command = AsyncMock(return_value=record)
    service.saved = SimpleNamespace(
        checkpoints=SimpleNamespace(
            repository=SimpleNamespace(inventory=AsyncMock(return_value=[]))
        ),
        edits=object(),
        limits=object(),
    )
    monkeypatch.setattr(execution, "capture_checkpoint", AsyncMock(side_effect=OSError()))
    owner = SimpleNamespace(
        thread_id=str(uuid4()),
        user_id=str(uuid4()),
        project_id=str(uuid4()),
        generation="a" * 64,
        task_id=str(uuid4()),
    )
    actual = await service.run(owner, record.operation_id, record.spec, "private")
    assert actual["state"] == "failed" and actual["blocker"] == "preparation_failed"
    service.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_count", [0, 1, 2])
async def test_repair_limit_survives_attempts_and_does_not_replace_recipe(
    monkeypatch, repair_count
):
    current = state(repairs=repair_count)
    spec = running().spec.model_copy(
        update={"criterion_id": "test", "target": "src/hello_world.py"}
    )
    db = SimpleNamespace(
        scalar=AsyncMock(return_value={"verification": {"status": "failed"}}), execute=AsyncMock()
    )
    saved = AsyncMock()
    monkeypatch.setattr(recipes, "save_checkpoint", saved)
    row = {"task_id": uuid4(), "verification_recipes": {"test": recipes.recipe(spec)}}
    if repair_count == 2:
        with pytest.raises(HarnessFailure, match="usage_limit_exceeded"):
            await recipes.bind_recipe(
                db, row, SimpleNamespace(state=current, continuation=None), spec
            )
        saved.assert_not_awaited()
    else:
        await recipes.bind_recipe(db, row, SimpleNamespace(state=current, continuation=None), spec)
        assert saved.await_args.kwargs["state"].repairs == repair_count + 1
    db.execute.assert_not_awaited()  # Already-bound recipe is never rewritten.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,expected", [("cancelled", "cancelled"), ("binding_changed", "failed")]
)
async def test_publication_rechecks_stop_and_generation_under_task_lock(
    monkeypatch, failure, expected
):
    old = running()
    db = SimpleNamespace()
    repo = journal.IdeCommandRepository(None)
    repo._transaction = lambda operation: operation(db)
    row = {"task_id": old.task_id, "job_status": "PROCESSING", "job_payload": {}}
    if failure == "cancelled":
        row["job_payload"]["_cancel_requested_v1"] = True
    monkeypatch.setattr(journal, "owned_row", AsyncMock(return_value=row))
    monkeypatch.setattr(journal.records, "read", AsyncMock(return_value=old))
    monkeypatch.setattr(journal.records, "save", AsyncMock())
    monkeypatch.setattr(
        journal, "current_generation", AsyncMock(side_effect=HarnessFailure(failure))
    )
    completed = AsyncMock()
    monkeypatch.setattr(journal, "complete", completed)
    monkeypatch.setattr(journal, "release_snapshot", AsyncMock())
    receipt = await repo.transition(
        object(),
        old.operation_id,
        state="completed",
        result=result(),
        final_revision="current",
        output_complete=True,
        cleanup_confirmed=True,
        verification={"status": "passed", "recipe_digest": "a" * 64},
    )
    assert receipt.state == expected and receipt.verification["status"] == "blocked"
    assert completed.await_args.args[2].state != "completed"


@pytest.mark.asyncio
async def test_racing_observer_reads_committed_receipt_without_second_finalization():
    record = running()
    terminal = record.advance(
        state="failed",
        cleanup_confirmed=True,
        final_revision="final",
        failure_reason="output_unavailable",
    )
    service = subject(record)
    service.repo.command_status.side_effect = [record, terminal]
    service.repo.transition.side_effect = HarnessFailure("operation_unknown")
    service.request.return_value = {
        "running": False,
        "cleanup_confirmed": True,
        "receipt": None,
        "final_revision": "final",
    }
    actual = await service.status(
        SimpleNamespace(thread_id="thread"), record.operation_id, "private"
    )
    assert actual["state"] == "failed" and actual["blocker"] == "output_unavailable"
    service.repo.transition.assert_awaited_once()
