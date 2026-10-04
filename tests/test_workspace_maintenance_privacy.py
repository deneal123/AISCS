"""Maintenance diagnostics must never serialize exception bodies or container IDs."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
from application.lifecycle import WorkspaceRegistry

from drivers import docker_cli
from drivers.base import ContainerRef, DriverError


@pytest.mark.asyncio
async def test_workspace_maintenance_failure_logs_only_bounded_diagnostic(caplog):
    registry = WorkspaceRegistry(None)
    completed = asyncio.Event()
    calls = 0

    async def reap():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private-exception-marker https://private.example/token")
        completed.set()

    registry.reap = reap
    registry.reconcile = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="workspace-sidecar.core"):
        task = asyncio.create_task(registry.reap_forever(interval_sec=0))
        try:
            await asyncio.wait_for(completed.wait(), timeout=1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert "private-exception-marker" not in caplog.text
    records = [record for record in caplog.records if record.name == "workspace-sidecar.core"]
    assert len(records) == 1
    assert records[0].exc_info is None
    assert records[0].failure_code == "maintenance_failed"
    assert records[0].component == "workspace_lifecycle"


@pytest.mark.asyncio
async def test_failed_process_cleanup_does_not_log_container_identity(monkeypatch, caplog):
    monkeypatch.setattr(docker_cli, "_docker", AsyncMock(side_effect=DriverError("private-marker")))
    with caplog.at_level(logging.ERROR, logger="workspace-sidecar.docker"):
        await docker_cli.DockerCliDriver()._kill_process_group(
            ContainerRef("docker", "private-container-marker")
        )
    assert "private-container-marker" not in caplog.text
    assert "private-marker" not in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None
    assert caplog.records[0].failure_code == "process_cleanup_failed"
