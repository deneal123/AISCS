"""A lost Docker create reply must not free capacity or recover an unissued sandbox."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from application.lifecycle import TooManyWorkspaces, WorkspaceRegistry
from application.recovery import LABEL_MANIFEST, mint_manifest, parse_manifest
from domain.policy import WorkspacePolicy

from drivers import docker_cli
from drivers.base import ContainerRef, DriverError, ManagedContainer


@pytest.fixture(autouse=True)
def owner_secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "fixture-owner-key-not-a-deployment-secret")


@pytest.mark.parametrize("cancel", [False, True])
async def test_unknown_create_reply_retains_capacity_until_owned_container_found(
    monkeypatch, caplog, cancel
):
    entered = asyncio.Event()
    labels = {}
    ref = ContainerRef("docker", "c" * 64)

    async def command(*args):
        assert args[0] == "create", "unknown create must not be automatically retried or started"
        labels.update(dict(arg.split("=", 1) for arg in args if arg.startswith("gpthub.workspace")))
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise DriverError("private-lost-create-reply")

    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    inventory = AsyncMock(return_value=[])
    destroy = AsyncMock()
    monkeypatch.setattr(driver, "list_managed", inventory)
    monkeypatch.setattr(driver, "destroy", destroy)
    registry = WorkspaceRegistry(driver, max_workspaces=1)
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    await asyncio.wait_for(entered.wait(), 1)
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else DriverError) as caught:
        await task
    assert "private-lost-create-reply" not in str(caught.value)
    assert "private-lost-create-reply" not in caplog.text
    assert registry.count() == 1
    assert not registry._items
    assert registry.health()["creation_pending"] == 1
    assert await registry.reconcile() == 0
    assert registry.count() == 1, "empty inventory before expiry is not proof of non-creation"
    with pytest.raises(TooManyWorkspaces):
        await registry.create("other", WorkspacePolicy())
    inventory.return_value = [ManagedContainer(ref, labels)]
    assert await registry.reconcile() == 0
    assert registry.count() == 0
    destroy.assert_awaited_once_with(ref)


async def test_reconcile_does_not_adopt_container_before_create_handoff(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    ref = ContainerRef("docker", "d" * 64)
    found = []

    async def create(_workspace_id, _policy, *, labels):
        found.append(ManagedContainer(ref, labels))
        entered.set()
        await release.wait()
        return ref

    fake = type("Driver", (), {})()
    fake.create = create
    fake.verify_isolation = AsyncMock()
    fake.destroy = AsyncMock()
    fake.list_managed = AsyncMock(side_effect=lambda: list(found))
    registry = WorkspaceRegistry(fake)
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await registry.reconcile() == 0
        assert not registry._items
        assert registry.count() == 1
        release.set()
        item, _token = await task
        assert registry.count() == 1
        assert item.recovered is False
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_expired_unknown_requires_successful_inventory_before_capacity_release(monkeypatch):
    async def command(*_args):
        raise DriverError("private-lost-create-reply")

    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    inventory = AsyncMock(side_effect=DriverError("private-inventory-body"))
    monkeypatch.setattr(driver, "list_managed", inventory)
    registry = WorkspaceRegistry(driver, max_workspaces=1)
    with pytest.raises(DriverError):
        await registry.create("owner", WorkspacePolicy(), ttl_sec=1)
    monkeypatch.setattr("application.lifecycle.time.time", lambda: time.monotonic() + 10**12)
    with pytest.raises(DriverError):
        await registry.reconcile()
    assert registry.count() == 1
    inventory.side_effect = None
    inventory.return_value = []
    assert await registry.reconcile() == 0
    assert registry.count() == 0


@pytest.mark.parametrize("foreign_manifest", [False, True])
async def test_late_container_and_foreign_manifest_are_not_confused(monkeypatch, foreign_manifest):
    labels = {}

    async def command(*args):
        labels.update(dict(arg.split("=", 1) for arg in args if arg.startswith("gpthub.workspace")))
        raise DriverError("private-lost-create-reply")

    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    inventory = AsyncMock(return_value=[])
    destroy = AsyncMock()
    monkeypatch.setattr(driver, "list_managed", inventory)
    monkeypatch.setattr(driver, "destroy", destroy)
    registry = WorkspaceRegistry(driver)
    with pytest.raises(DriverError):
        await registry.create("owner", WorkspacePolicy(), ttl_sec=1)
    manifest = parse_manifest(labels[LABEL_MANIFEST])
    assert manifest is not None
    if foreign_manifest:
        labels[LABEL_MANIFEST] = mint_manifest(
            manifest.workspace_id, "different-owner", manifest.expires_at, manifest.policy
        )
    else:
        # A trustworthy empty inventory at expiry retires the uncertainty.
        monkeypatch.setattr("application.lifecycle.time.time", lambda: manifest.expires_at + 1)
        await registry.reconcile()
        assert registry.count() == 0
    ref = ContainerRef("docker", "e" * 64)
    inventory.return_value = [ManagedContainer(ref, labels)]
    assert await registry.reconcile() == 0
    if foreign_manifest:
        destroy.assert_not_awaited()
        assert registry.count() == 1
        assert not registry._items
    else:
        destroy.assert_awaited_once_with(ref)
        assert registry.count() == 0


async def test_definitive_create_rejection_does_not_reserve_unknown_capacity(monkeypatch):
    monkeypatch.setattr(docker_cli, "_docker", AsyncMock(return_value=(1, "", "private-rejection")))
    registry = WorkspaceRegistry(docker_cli.DockerCliDriver())
    with pytest.raises(DriverError):
        await registry.create("owner", WorkspacePolicy())
    assert registry.count() == 0
    assert registry.health()["creation_pending"] == 0


@pytest.mark.parametrize("reply", ["", "unexpected-output", "f" * 12, "../other-container"])
async def test_malformed_success_reply_never_starts_or_deletes_guessed_target(monkeypatch, reply):
    command = AsyncMock(return_value=(0, reply, ""))
    monkeypatch.setattr(docker_cli, "_docker", command)
    driver = docker_cli.DockerCliDriver()
    destroy = AsyncMock()
    monkeypatch.setattr(driver, "destroy", destroy)
    registry = WorkspaceRegistry(driver)
    with pytest.raises(DriverError):
        await registry.create("owner", WorkspacePolicy())
    assert command.await_count == 1
    destroy.assert_not_awaited()
    assert registry.count() == 1
    assert registry.health()["creation_pending"] == 1


async def test_repeated_cancel_preserves_unknown_intent_handoff(monkeypatch):
    entered = asyncio.Event()

    async def command(*_args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(docker_cli, "_docker", command)
    registry = WorkspaceRegistry(docker_cli.DockerCliDriver())
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        await registry._lock.acquire()
        try:
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                assert registry.count() == 1
        finally:
            registry._lock.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert registry.count() == 1
        assert not registry._reserved
        assert registry.health()["creation_pending"] == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
