"""Transient maintenance failures retain admission and cannot kill retry polling."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from application.documents.builds import DocumentBuildManager
from application.documents.projects import DocumentProjectError
from infrastructure import document_compiler
from infrastructure.document_compiler import DockerDocumentCompiler


@pytest.mark.asyncio
async def test_startup_inventory_failure_defers_builds_until_successful_reconciliation():
    registry = SimpleNamespace(active_workspaces=AsyncMock(side_effect=OSError("private-marker")))
    compiler = SimpleNamespace(
        reconcile=AsyncMock(return_value=0), prepare=AsyncMock(), health=lambda: {}
    )
    manager = DocumentBuildManager(compiler, None, None)
    manager.recover = AsyncMock()
    manager._reserve_manifest = AsyncMock()
    manager._start_reserved = AsyncMock(return_value="accepted")
    await manager.reconcile_registry(registry)
    with pytest.raises(DocumentProjectError, match="runtime_unavailable"):
        await manager.start(
            registry,
            SimpleNamespace(workspace_id="owned"),
            project_path="paper",
            expected_revision="rev",
            final=False,
        )
    manager._start_reserved.assert_not_awaited()
    compiler.prepare.assert_not_awaited()
    health = manager.health()
    assert health["reconciliation_failures"] == 1
    assert health["reconciliation_unavailable"] is True
    assert "private-marker" not in str(health)
    registry.active_workspaces.side_effect = None
    registry.active_workspaces.return_value = ()
    await manager.reconcile_registry(registry)
    assert manager.health()["reconciliation_unavailable"] is False
    assert (
        await manager.start(
            registry,
            SimpleNamespace(workspace_id="owned"),
            project_path="paper",
            expected_revision="rev",
            final=False,
        )
        == "accepted"
    )


@pytest.mark.asyncio
async def test_compiler_reconciliation_exception_does_not_terminate_maintenance_task():
    recovered = asyncio.Event()
    calls = 0

    async def reconcile():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("private-marker")
        recovered.set()

    registry = SimpleNamespace(active_workspaces=AsyncMock(return_value=()))
    manager = DocumentBuildManager(
        SimpleNamespace(reconcile=reconcile, health=lambda: {}), None, None
    )
    task = asyncio.create_task(manager.reconcile_forever(registry, interval_sec=0))
    try:
        await asyncio.wait_for(recovered.wait(), timeout=1)
        assert not task.done()
        assert manager.health()["reconciliation_failures"] == 1
        assert manager.health()["reconciliation_unavailable"] is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_native_malformed_docker_inventory_is_bounded_and_retried(monkeypatch):
    command = AsyncMock(side_effect=[(0, b"\xff"), (0, b"")])
    monkeypatch.setattr(document_compiler, "_command", command)
    manager = DocumentBuildManager(DockerDocumentCompiler(), None, None)
    registry = SimpleNamespace(active_workspaces=AsyncMock(return_value=()))
    await manager.reconcile_registry(registry)
    assert manager.health()["reconciliation_unavailable"] is True
    assert manager.health()["reconciliation_failures"] == 1
    await manager.reconcile_registry(registry)
    assert manager.health()["reconciliation_unavailable"] is False
    assert command.await_count == 2


@pytest.mark.asyncio
async def test_shutdown_cancellation_is_not_reclassified_as_retryable_outage():
    registry = SimpleNamespace(active_workspaces=AsyncMock(side_effect=asyncio.CancelledError()))
    manager = DocumentBuildManager(DockerDocumentCompiler(), None, None)
    with pytest.raises(asyncio.CancelledError):
        await manager.reconcile_registry(registry)
    assert manager.health()["reconciliation_failures"] == 0
