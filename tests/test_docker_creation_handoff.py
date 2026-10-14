"""An acknowledged create remains owned until start and registry handoff complete."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from application.lifecycle import TooManyWorkspaces, WorkspaceRegistry
from domain.policy import WorkspacePolicy

from drivers import docker_cli
from drivers.base import ContainerRef, DriverError


@pytest.mark.parametrize("failure", ["cancel", "timeout", "exit"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_start_failure_keeps_owned_cleanup_debt(monkeypatch, caplog, failure, cleanup_fails):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "fixture-owner-key-not-a-deployment-secret")
    entered = asyncio.Event()
    ref = ContainerRef("docker", "a" * 64)

    async def command(*args):
        if args[0] == "create":
            return 0, ref.container_id + "\n", ""
        assert args == ("start", ref.container_id)
        entered.set()
        if failure == "cancel":
            await asyncio.Event().wait()
        if failure == "timeout":
            raise DriverError("private-start-body")
        return 1, "", "private-start-body"

    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    destroy = AsyncMock(side_effect=DriverError("private-cleanup-body") if cleanup_fails else None)
    monkeypatch.setattr(driver, "destroy", destroy)
    registry = WorkspaceRegistry(driver, max_workspaces=1)
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    await asyncio.wait_for(entered.wait(), 1)
    if failure == "cancel":
        task.cancel()
    with pytest.raises(asyncio.CancelledError if failure == "cancel" else DriverError) as caught:
        await asyncio.wait_for(task, 1)
    assert "private-start-body" not in str(caught.value)
    assert "private-cleanup-body" not in str(caught.value)
    assert "private-start-body" not in caplog.text
    assert "private-cleanup-body" not in caplog.text
    assert not registry._items
    assert not registry._reserved
    assert registry.count() == int(cleanup_fails)
    assert destroy.await_count >= 1
    assert all(call.args == (ref,) for call in destroy.await_args_list)
    if cleanup_fails:
        with pytest.raises(TooManyWorkspaces):
            await registry.create("other", WorkspacePolicy())
        destroy.side_effect = None
        key, (owned, reason, attempts, _) = next(iter(registry._pending_cleanup.items()))
        registry._pending_cleanup[key] = (owned, reason, attempts, 0)
        await registry.reap()
        assert registry.count() == 0


async def test_repeated_cancel_does_not_interrupt_owned_container_cleanup(monkeypatch):
    start = asyncio.Event()
    cleanup = asyncio.Event()
    release = asyncio.Event()
    ref = ContainerRef("docker", "b" * 64)

    async def command(*args):
        if args[0] == "create":
            return 0, ref.container_id, ""
        start.set()
        await asyncio.Event().wait()

    async def destroy(owned):
        assert owned == ref
        cleanup.set()
        await release.wait()

    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    remover = AsyncMock(side_effect=destroy)
    monkeypatch.setattr(driver, "destroy", remover)
    task = asyncio.create_task(driver.create("fixture", WorkspacePolicy()))
    try:
        await asyncio.wait_for(start.wait(), 1)
        task.cancel()
        await asyncio.wait_for(cleanup.wait(), 1)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        remover.assert_awaited_once_with(ref)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
