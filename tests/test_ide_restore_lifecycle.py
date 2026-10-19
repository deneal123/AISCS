"""Restore is preparation of a fresh allocation, not a write to an active repo."""

import asyncio
import io
import time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from application.allocations import AllocationConflict, AllocationPending, WorkspaceAllocation
from application.ide_bundles import IdeBundleService
from application.lifecycle import TooManyWorkspaces, WorkspaceRegistry
from domain.policy import WorkspacePolicy
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits

from drivers.base import ContainerRef, ManagedContainer

LIMITS = BundleLimits(16, 1024, 4096, 16384, 8192, 8)
DIGEST = "a" * 64


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "restore-fixture-not-a-deployment-secret")


def driver():
    found = []

    async def create(identity, policy, *, labels):
        ref = ContainerRef("fixture", identity)
        found.append(ManagedContainer(ref, labels))
        return ref

    async def destroy(ref):
        found[:] = [entry for entry in found if entry.ref != ref]

    return type(
        "Driver",
        (),
        {
            "name": "fixture",
            "create": AsyncMock(side_effect=create),
            "destroy": AsyncMock(side_effect=destroy),
            "verify_isolation": AsyncMock(),
            "list_managed": AsyncMock(side_effect=lambda: list(found)),
        },
    )()


def intent():
    return WorkspaceAllocation(uuid4(), int(time.time()) + 600)


async def restore(registry, allocation, source=None, digest=DIGEST):
    return await registry.create_restored(
        "owner",
        WorkspacePolicy(),
        allocation=allocation,
        source=source or io.BytesIO(b"capsule"),
        limits=LIMITS,
        expected_size=7,
        expected_sha256=digest,
    )


async def test_restore_is_unpublished_and_occupies_capacity_until_confirmed(monkeypatch):
    entered, resume = asyncio.Event(), asyncio.Event()

    async def materialize(*args, **kwargs):
        entered.set()
        await resume.wait()
        return 2

    monkeypatch.setattr(IdeBundleService, "restore", materialize)
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    task = asyncio.create_task(restore(registry, allocation))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert registry.health()["active"] == 0 and registry.count() == 1
        with pytest.raises(AllocationPending):
            registry.lookup_allocation("owner", allocation)
        with pytest.raises(AllocationPending):
            await restore(registry, allocation)
        with pytest.raises(TooManyWorkspaces):
            await registry.create("other", WorkspacePolicy(), allocation=intent())
        marker.assert_not_awaited()
    finally:
        resume.set()
        item, token = await task
    assert registry.get(item.workspace_id, "owner", token) is item
    assert registry.lookup_allocation("owner", allocation) is item
    assert marker.await_args.kwargs == {"write": True}
    fake.create.assert_awaited_once()


async def test_partial_restore_is_retired_without_a_ready_marker(monkeypatch):
    monkeypatch.setattr(IdeBundleService, "restore", AsyncMock(side_effect=BundleFailure()))
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    registry = WorkspaceRegistry(fake)
    with pytest.raises(BundleFailure):
        await restore(registry, allocation)
    marker.assert_not_awaited()
    fake.destroy.assert_awaited_once()
    assert registry.count() == 0 and not await fake.list_managed()


async def test_replay_is_bound_to_the_original_snapshot_and_does_not_restore_twice(monkeypatch):
    materialize = AsyncMock(return_value=2)
    monkeypatch.setattr(IdeBundleService, "restore", materialize)
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    registry = WorkspaceRegistry(fake)
    first, _ = await restore(registry, allocation)
    second, _ = await restore(registry, allocation)
    assert first is second
    with pytest.raises(AllocationConflict):
        await restore(registry, allocation, digest="b" * 64)
    with pytest.raises(AllocationConflict):
        await registry.create("owner", WorkspacePolicy(), allocation=allocation)
    materialize.assert_awaited_once()
    marker.assert_awaited_once()


async def test_restart_never_adopts_a_container_without_a_confirmed_restore_receipt(monkeypatch):
    monkeypatch.setattr(IdeBundleService, "restore", AsyncMock(return_value=2))
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    await restore(WorkspaceRegistry(fake), allocation)
    marker.reset_mock()
    marker.return_value = False
    fresh = WorkspaceRegistry(fake)
    assert await fresh.reconcile() == 0
    assert fresh.health()["active"] == 0 and fresh.count() == 0
    assert marker.await_args.kwargs == {"write": False}
    fake.destroy.assert_awaited_once()


async def test_restart_with_receipt_preserves_generation_and_snapshot_identity(monkeypatch):
    materialize = AsyncMock(return_value=2)
    monkeypatch.setattr(IdeBundleService, "restore", materialize)
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    original, _ = await restore(WorkspaceRegistry(fake), allocation)
    fresh = WorkspaceRegistry(fake)
    assert await fresh.reconcile() == 1
    recovered = fresh.lookup_allocation("owner", allocation)
    assert recovered.ref == original.ref and recovered.recovered
    assert recovered.restore_snapshot == original.restore_snapshot
    second, _ = await restore(fresh, allocation)
    assert second is recovered
    materialize.assert_awaited_once()


async def test_unavailable_receipt_keeps_recovery_pending_without_destroy_or_adoption(monkeypatch):
    monkeypatch.setattr(IdeBundleService, "restore", AsyncMock(return_value=2))
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker, raising=False)
    fake, allocation = driver(), intent()
    await restore(WorkspaceRegistry(fake), allocation)
    marker.side_effect = BundleFailure("ide_bundle_unavailable")
    fresh = WorkspaceRegistry(fake, max_workspaces=1)
    assert await fresh.reconcile() == 0
    assert fresh.health()["recovery_pending"] == 1 and fresh.count() == 1
    fake.destroy.assert_not_awaited()
    with pytest.raises(AllocationPending):
        await restore(fresh, allocation)
    marker.side_effect = None
    assert await fresh.reconcile() == 1


async def test_cancelled_restore_keeps_cleanup_debt_and_never_becomes_active(monkeypatch):
    entered = asyncio.Event()

    async def materialize(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(IdeBundleService, "restore", materialize)
    marker = AsyncMock(return_value=True)
    monkeypatch.setattr(IdeBundleService, "receipt", marker)
    fake, allocation = driver(), intent()
    fake.destroy.side_effect = RuntimeError("fixture cleanup unavailable")
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    task = asyncio.create_task(restore(registry, allocation))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert registry.health()["active"] == 0
    assert registry.health()["pending_cleanup"] == registry.count() == 1
    marker.assert_not_awaited()
    with pytest.raises(AllocationPending):
        await restore(registry, allocation)
    with pytest.raises(TooManyWorkspaces):
        await restore(registry, intent())


@pytest.mark.parametrize("result", [False, BundleFailure("ide_bundle_unavailable")])
async def test_restore_without_confirmed_publication_never_issues_ready(monkeypatch, result):
    monkeypatch.setattr(IdeBundleService, "restore", AsyncMock(return_value=2))
    marker = AsyncMock(return_value=result) if result is False else AsyncMock(side_effect=result)
    monkeypatch.setattr(IdeBundleService, "receipt", marker)
    fake, allocation = driver(), intent()
    registry = WorkspaceRegistry(fake)
    with pytest.raises(BundleFailure):
        await restore(registry, allocation)
    assert registry.health()["active"] == 0
    fake.destroy.assert_awaited_once()


async def test_deadline_expiring_during_restore_cannot_issue_a_ready_token(monkeypatch):
    allocation = intent()

    async def materialize(*args, **kwargs):
        monkeypatch.setattr("application.allocations.time.time", lambda: allocation.expires_at + 1)

    monkeypatch.setattr(IdeBundleService, "restore", materialize)
    monkeypatch.setattr(IdeBundleService, "receipt", AsyncMock(return_value=True))
    fake = driver()
    registry = WorkspaceRegistry(fake)
    from application.allocations import AllocationExpired

    with pytest.raises(AllocationExpired):
        await restore(registry, allocation)
    assert registry.health()["active"] == 0
    fake.destroy.assert_awaited_once()
