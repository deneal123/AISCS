"""A signed manifest is ownership evidence, not proof of current runtime isolation."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from application.lifecycle import WorkspaceNotFound, WorkspaceRegistry
from application.recovery import LABEL_MANIFEST, mint_manifest
from domain.ownership import mint
from domain.policy import WorkspacePolicy

from drivers.base import ContainerRef, DriverError, IsolationUnverified, ManagedContainer


@pytest.fixture
def recovered_fixture(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "fixture-owner-key-not-a-deployment-secret")
    policy = WorkspacePolicy()
    ref = ContainerRef("fixture", "owned-fixture")
    labels = {LABEL_MANIFEST: mint_manifest("fixture", "owner", time.time() + 600, policy)}
    driver = type("Driver", (), {})()
    driver.list_managed = AsyncMock(return_value=[ManagedContainer(ref, labels)])
    driver.verify_isolation = AsyncMock()
    driver.destroy = AsyncMock()
    return driver, ref, policy


async def test_recovery_verifies_isolation_before_owner_can_access(recovered_fixture):
    driver, ref, policy = recovered_fixture
    registry = WorkspaceRegistry(driver)
    assert await registry.reconcile() == 1
    driver.verify_isolation.assert_awaited_once_with(ref, policy)
    assert registry.get("fixture", "owner", mint("fixture", "owner")).recovered


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_known_isolation_violation_is_not_recovered(recovered_fixture, caplog, cleanup_fails):
    driver, ref, _ = recovered_fixture
    driver.verify_isolation.side_effect = IsolationUnverified("private-isolation-body")
    if cleanup_fails:
        driver.destroy.side_effect = DriverError("private-cleanup-body")
    registry = WorkspaceRegistry(driver)
    assert await registry.reconcile() == 0
    with pytest.raises(WorkspaceNotFound):
        registry.get("fixture", "owner", mint("fixture", "owner"))
    assert registry.count() == int(cleanup_fails)
    driver.destroy.assert_awaited_once_with(ref)
    assert "private-isolation-body" not in caplog.text
    assert "private-cleanup-body" not in caplog.text


@pytest.mark.parametrize("failure", [DriverError, RuntimeError])
async def test_unknown_inspection_retains_capacity_without_deleting_files(
    recovered_fixture, failure, caplog
):
    driver, _, _ = recovered_fixture
    driver.verify_isolation.side_effect = failure("private-inspection-body")
    registry = WorkspaceRegistry(driver)
    assert await registry.reconcile() == 0
    assert registry.count() == 1
    assert registry.health()["recovery_pending"] == 1
    driver.destroy.assert_not_awaited()
    with pytest.raises(WorkspaceNotFound):
        registry.get("fixture", "owner", mint("fixture", "owner"))
    driver.verify_isolation.side_effect = None
    assert await registry.reconcile() == 1
    assert registry.count() == 1
    assert registry.health()["recovery_pending"] == 0
    assert registry.get("fixture", "owner", mint("fixture", "owner")).recovered
    assert "private-inspection-body" not in caplog.text
    records = [record for record in caplog.records if hasattr(record, "failure_code")]
    assert records
    assert all(record.failure_code == "inspection_unavailable" for record in records)
    assert all(record.exc_info is None and record.stack_info is None for record in records)


async def test_cancelled_inspection_never_publishes_recovered_workspace(recovered_fixture):
    driver, _, _ = recovered_fixture
    entered = asyncio.Event()

    async def inspect(*_):
        entered.set()
        await asyncio.Event().wait()

    driver.verify_isolation.side_effect = inspect
    registry = WorkspaceRegistry(driver)
    task = asyncio.create_task(registry.reconcile())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not registry._items
        assert registry.count() == 1
        driver.destroy.assert_not_awaited()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_inspection_outage_does_not_hide_other_verified_workspace(recovered_fixture):
    driver, ref, policy = recovered_fixture
    other_ref = ContainerRef("fixture", "other-owned-fixture")
    driver.list_managed.return_value.append(
        ManagedContainer(
            other_ref,
            {LABEL_MANIFEST: mint_manifest("other", "owner", time.time() + 600, policy)},
        )
    )
    driver.verify_isolation.side_effect = [DriverError("private-body"), None]
    registry = WorkspaceRegistry(driver)
    assert await registry.reconcile() == 1
    assert registry.count() == 2
    assert registry.get("other", "owner", mint("other", "owner")).ref == other_ref
    assert registry._recovery_pending["fixture"].ref == ref
    driver.destroy.assert_not_awaited()


async def test_concurrent_violation_cleanup_cannot_be_followed_by_stale_publication(
    recovered_fixture,
):
    driver, ref, _ = recovered_fixture
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def inspect(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        else:
            raise IsolationUnverified("private-violation-body")

    driver.verify_isolation.side_effect = inspect
    registry = WorkspaceRegistry(driver)
    first = asyncio.create_task(registry.reconcile())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await registry.reconcile() == 0
        driver.destroy.assert_awaited_once_with(ref)
        release.set()
        assert await first == 0
        assert not registry._items
        assert registry.count() == 0
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("code,reply", [(1, ""), (0, "not-json"), (0, "[]"), (0, "{}")])
async def test_unusable_inspection_is_unknown_not_proven_violation(monkeypatch, code, reply):
    from drivers import docker_cli

    command = AsyncMock(return_value=(code, reply, "private-docker-inspection-body"))
    monkeypatch.setattr(docker_cli, "_docker", command)
    with pytest.raises(DriverError, match="isolation inspection unavailable"):
        await docker_cli.DockerCliDriver().verify_isolation(
            ContainerRef("docker", "owned-fixture"), WorkspacePolicy()
        )
