"""Command facts never replace task verification or expire with Redis leases."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from service.services.chat.application.workspace_collaboration import (
    CollaborationUnavailable,
    WorkspaceCapability,
    WorkspaceCollaborationStore,
)
from service.services.chat.domain.ide.commands import CommandRecord, CommandSpec
from service.services.chat.persistence.harness import effects
from service.services.chat.persistence.harness.commands import state
from service.services.chat.persistence.harness.commands.gate import (
    IdeCommandBusy,
    require_mutation_available,
)
from service.shared.harness_protocol import EffectResult, HarnessFailure


def command(**changes):
    return CommandRecord.model_validate(
        {
            "operation_id": uuid4(),
            "task_id": uuid4(),
            "repository_id": uuid4(),
            "workspace_id": "workspace",
            "generation": "a" * 64,
            "attempt_id": uuid4(),
            "epoch": 1,
            "spec": {"profile": "python_script", "target": "src/hello.py"},
            **changes,
        }
    )


def running(**changes):
    return command(
        state="running",
        snapshot_id=uuid4(),
        snapshot_digest="b" * 64,
        source_revision="tree1",
        engine_id="c" * 64,
        container_id="d" * 64,
        **changes,
    )


def result(**changes):
    return {
        "exit_code": 0,
        "stdout": "hello\n",
        "stderr": "",
        "truncated": False,
        "duration_sec": 0.1,
        "timed_out": False,
        **changes,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"profile": "shell", "command": " "},
        {"profile": "shell", "command": "pwd\nls"},
        {"profile": "shell", "command": "pwd", "expected_stdout": "hello"},
        {"profile": "shell", "command": "pwd", "target": "hello.py"},
        {"profile": "python_script", "target": "../escape.py"},
        {"profile": "python_script", "target": "/etc/passwd"},
        {"profile": "python_script", "target": "hello.txt"},
        {"profile": "python_script", "target": "hello.py", "command": "pwd"},
        {"profile": "pytest", "target": "tests", "timeout_sec": True},
        {"profile": "pytest", "target": "tests", "capability": "private"},
    ],
)
def test_invalid_recipes_are_closed_and_path_errors_are_validation_errors(payload):
    with pytest.raises(ValidationError):
        CommandSpec.model_validate(payload)


@pytest.mark.parametrize(
    "profile,target",
    [
        ("python_script", "src/hello world.py"),
        ("unittest", "tests"),
        ("pytest", "tests/test_a.py"),
    ],
)
def test_versioned_recipes_are_accepted(profile, target):
    assert CommandSpec(profile=profile, target=target).target == target


@pytest.mark.parametrize(
    "updates",
    [
        {"state": "running"},
        {"snapshot_id": uuid4()},
        {"engine_id": "c" * 64},
    ],
)
def test_process_cannot_start_without_confirmed_snapshot_and_identity(updates):
    with pytest.raises(ValidationError):
        command(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"state": "completed", "result": result(), "final_revision": "tree2"},
        {"state": "completed", "result": result(), "cleanup_confirmed": True},
        {
            "state": "completed",
            "result": result(),
            "cleanup_confirmed": True,
            "final_revision": "tree2",
            "output_complete": False,
        },
        {
            "state": "completed",
            "result": result(exit_code=1),
            "cleanup_confirmed": True,
            "final_revision": "tree2",
            "output_complete": True,
        },
        {
            "state": "completed",
            "result": result(timed_out=True),
            "cleanup_confirmed": True,
            "final_revision": "tree2",
            "output_complete": True,
        },
        {"state": "cancelled"},
    ],
)
def test_unconfirmed_exit_or_cleanup_cannot_release_command(updates):
    with pytest.raises(ValidationError):
        running().advance(**updates)


@pytest.mark.asyncio
async def test_replaying_terminal_is_noop_and_changing_it_is_forbidden():
    old = running().advance(
        state="completed",
        result=result(),
        cleanup_confirmed=True,
        final_revision="tree2",
        output_complete=True,
    )
    db = SimpleNamespace(execute=AsyncMock())
    await state.save(db, old, old)
    db.execute.assert_not_awaited()
    with pytest.raises(HarnessFailure, match="operation_unknown"):
        await state.save(db, old, old.advance(state="unknown"))
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_stop_can_retire_running_but_not_unknown_cleanup():
    old = running()
    db = SimpleNamespace(execute=AsyncMock())
    await state.save(db, old, old.advance(state="cancelled", cleanup_confirmed=True))
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "updates",
    [
        {"operation_id": uuid4()},
        {"epoch": 2},
        {"engine_id": "e" * 64},
        {"source_revision": "different"},
        {"spec": {"profile": "shell", "command": "pwd"}},
    ],
)
async def test_command_identity_and_intent_are_immutable(updates):
    old = running()
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="operation_conflict"):
        await state.save(db, old, old.advance(**updates))
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_retains_same_command_gate_until_reconciliation():
    old = running()
    db = SimpleNamespace(execute=AsyncMock())
    await state.save(db, old, old.advance(state="unknown"))
    assert db.execute.await_args.args[1]["state"] == "unknown"
    # No transition from uncertainty back to a dispatchable phase.
    with pytest.raises(HarnessFailure, match="operation_unknown"):
        await state.save(db, old.advance(state="unknown"), old.advance(state="dispatching"))


class Connector:
    def __init__(self, busy=False, unavailable=False):
        self.db = SimpleNamespace(scalar=AsyncMock(return_value=busy))
        self.unavailable = unavailable

    @asynccontextmanager
    async def get_session_context(self):
        if self.unavailable:
            raise RuntimeError("private database detail")
        yield self.db


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["write", "exec", "snapshot", "revert", "import", "policy"])
async def test_postgres_gate_blocks_all_mutations_even_without_redis(mutation):
    connector = Connector(busy=True)
    with pytest.raises(IdeCommandBusy):
        await require_mutation_available(connector, "workspace", mutation)
    assert connector.db.scalar.await_args.args[1] == {"workspace": "workspace"}


@pytest.mark.asyncio
async def test_only_read_only_capture_is_exempt_and_database_failure_is_closed():
    connector = Connector(busy=True)
    await require_mutation_available(connector, "workspace", "capture")
    connector.db.scalar.assert_not_awaited()
    await require_mutation_available(Connector(), "workspace", "write")
    with pytest.raises(CollaborationUnavailable) as error:
        await require_mutation_available(Connector(unavailable=True), "workspace", "exec")
    assert "private" not in str(error.value)


@pytest.mark.asyncio
async def test_adapter_cannot_publish_command_success_or_its_own_verification(monkeypatch):
    identifier = uuid4()
    monkeypatch.setattr(
        effects,
        "read",
        AsyncMock(
            return_value={
                "status": "dispatched",
                "receipt": None,
                "intent": {"name": "ide_run_command"},
            }
        ),
    )
    db = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HarnessFailure, match="verification_missing"):
        await effects.record(
            db,
            {"task_id": uuid4()},
            EffectResult(
                operation_id=str(identifier),
                status="succeeded",
                text="done",
                charged=True,
            ),
            None,
        )
    db.execute.assert_not_awaited()


def test_missing_output_never_becomes_success_but_confirmed_cleanup_can_release_gate():
    old = running()
    failed = old.advance(
        state="failed",
        result=result(),
        cleanup_confirmed=True,
        final_revision="tree2",
        output_complete=False,
    )
    assert failed.state == "failed" and not failed.output_complete
    with pytest.raises(ValidationError):
        failed.advance(state="completed")
    with pytest.raises(ValidationError):
        old.advance(cleanup_confirmed="true")


@pytest.mark.asyncio
async def test_durable_gate_precedes_redis_activity_and_edit_lease():
    redis = SimpleNamespace(get=AsyncMock(), set=AsyncMock())
    guard = AsyncMock(side_effect=IdeCommandBusy())
    store = WorkspaceCollaborationStore(
        redis, workspace_id="workspace", expires_at=4102444800, mutation_guard=guard
    )
    actor = WorkspaceCapability("workspace", "actor", "ui", 4102444800)
    with pytest.raises(IdeCommandBusy):
        await store.preflight(actor, mutation="write", path="src/hello.py", fence=1)
    guard.assert_awaited_once_with("workspace", "write")
    redis.get.assert_not_awaited()
    redis.set.assert_not_awaited()
