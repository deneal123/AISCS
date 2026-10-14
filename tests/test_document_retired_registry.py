"""Retired workspaces cannot inflate document inventory or erase cleanup debt."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.builds import DocumentBuildManager


def _manager(state="ready", compiler_ref=""):
    compiler = SimpleNamespace(reconcile=AsyncMock(), health=lambda: {})
    manager = DocumentBuildManager(compiler, None, None)
    manager.recover = AsyncMock()
    manager._builds["build"] = SimpleNamespace(
        build_id="build", workspace_id="retired", state=state, compiler_ref=compiler_ref
    )
    manager._recovered_workspaces.add("retired")
    manager._cancel_requested.add("build")
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["ready", "preview_ready", "visual_pending", "failed", "cancelled"]
)
async def test_retired_finished_build_is_evicted_after_successful_inventory(state):
    manager = _manager(state)
    finished = asyncio.create_task(asyncio.sleep(0))
    await finished
    manager._tasks["build"] = finished
    await manager.reconcile_registry(SimpleNamespace(active_workspaces=AsyncMock(return_value=())))
    assert not manager._builds
    assert not manager._tasks
    assert not manager._cancel_requested
    assert "retired" not in manager._recovered_workspaces
    assert manager.health()["ready"] == manager.health()["visual_pending"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["registry", "compiler"])
async def test_failed_inventory_does_not_infer_workspace_removal(failure):
    manager = _manager()
    registry = SimpleNamespace(active_workspaces=AsyncMock(return_value=()))
    if failure == "registry":
        registry.active_workspaces.side_effect = OSError("private-marker")
    else:
        manager.compiler.reconcile.side_effect = OSError("private-marker")
    await manager.reconcile_registry(registry)
    assert "build" in manager._builds
    assert manager.health()["reconciliation_unavailable"] is True
    assert "private-marker" not in str(manager.health())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,compiler_ref", [("building", ""), ("ready", "a" * 64), ("visual_audit", "")]
)
async def test_retired_unsettled_build_keeps_cleanup_and_execution_obligation(state, compiler_ref):
    manager = _manager(state, compiler_ref)
    await manager.reconcile_registry(SimpleNamespace(active_workspaces=AsyncMock(return_value=())))
    assert "build" in manager._builds


@pytest.mark.asyncio
async def test_running_task_is_not_evicted_even_after_terminal_state_assignment():
    manager = _manager()
    task = asyncio.create_task(asyncio.Event().wait())
    manager._tasks["build"] = task
    try:
        await manager.reconcile_registry(
            SimpleNamespace(active_workspaces=AsyncMock(return_value=()))
        )
        assert manager._tasks["build"] is task
        assert "build" in manager._builds
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_workspace_appearing_during_compiler_await_is_preserved():
    manager = _manager()
    registry = SimpleNamespace(
        active_workspaces=AsyncMock(side_effect=[(), (SimpleNamespace(workspace_id="retired"),)])
    )
    await manager.reconcile_registry(registry)
    assert "build" in manager._builds


@pytest.mark.asyncio
async def test_second_inventory_outage_preserves_previously_recovered_records():
    manager = _manager()
    registry = SimpleNamespace(
        active_workspaces=AsyncMock(side_effect=[(), OSError("private-marker")])
    )
    await manager.reconcile_registry(registry)
    assert "build" in manager._builds
    assert "retired" in manager._recovered_workspaces
    assert manager.health()["reconciliation_unavailable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("locks", ["_workspace_starts", "_recovery_locks"])
async def test_in_flight_workspace_admission_retains_records_until_lock_released(locks):
    manager = _manager()
    lock = asyncio.Lock()
    getattr(manager, locks)["retired"] = lock
    registry = SimpleNamespace(active_workspaces=AsyncMock(return_value=()))
    async with lock:
        await manager.reconcile_registry(registry)
        assert "build" in manager._builds
    await manager.reconcile_registry(registry)
    assert "build" not in manager._builds
