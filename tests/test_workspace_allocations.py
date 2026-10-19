import asyncio
import time
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from application.allocations import (
    AllocationConflict,
    AllocationExpired,
    AllocationPending,
    WorkspaceAllocation,
)
from application.lifecycle import WorkspaceRegistry
from domain.contracts import HARD_TTL_SEC
from domain.ownership import verify
from domain.policy import WorkspacePolicy

from drivers.base import ContainerCreationUncertain, ContainerRef, ManagedContainer


@pytest.fixture(autouse=True)
def owner_secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "allocation-fixture-secret-not-a-deployment-key")


def allocation():
    return WorkspaceAllocation(uuid4(), int(time.time()) + 600)


def driver():
    containers = []

    async def create(workspace_id, _policy, *, labels):
        ref = ContainerRef("fixture", workspace_id)
        containers.append(ManagedContainer(ref, labels))
        return ref

    return type(
        "Driver",
        (),
        {
            "name": "fixture",
            "create": AsyncMock(side_effect=create),
            "verify_isolation": AsyncMock(),
            "destroy": AsyncMock(),
            "list_managed": AsyncMock(side_effect=lambda: containers),
        },
    )()


async def test_replay_reuses_container_even_at_capacity_without_renewing_deadline():
    fake = driver()
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    intent = allocation()
    first, _ = await registry.create("owner", WorkspacePolicy(), allocation=intent)
    second, token = await registry.create("owner", WorkspacePolicy(), allocation=intent)
    assert first is second
    assert first.expires_at == intent.expires_at
    assert int(token.partition(".")[0]) <= intent.expires_at
    verify(token, first.workspace_id, "owner")
    assert registry.count() == 1
    fake.create.assert_awaited_once()


async def test_parallel_duplicates_are_pending_not_another_container_or_quota_failure():
    fake = driver()
    entered, release = asyncio.Event(), asyncio.Event()
    original = fake.create.side_effect

    async def slow_create(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    fake.create.side_effect = slow_create
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    intent = allocation()
    first = asyncio.create_task(registry.create("owner", WorkspacePolicy(), allocation=intent))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        pending = await asyncio.gather(
            *(registry.create("owner", WorkspacePolicy(), allocation=intent) for _ in range(7)),
            return_exceptions=True,
        )
        assert all(isinstance(result, AllocationPending) for result in pending)
        assert registry.count() == 1
        fake.create.assert_awaited_once()
    finally:
        release.set()
        await first


async def test_different_repository_generations_and_owners_have_distinct_containers():
    fake = driver()
    registry = WorkspaceRegistry(fake)
    intent = allocation()
    first, _ = await registry.create("owner", WorkspacePolicy(), allocation=intent)
    second, _ = await registry.create("owner", WorkspacePolicy(), allocation=allocation())
    foreign, _ = await registry.create("other-owner", WorkspacePolicy(), allocation=intent)
    legacy, _ = await registry.create("owner", WorkspacePolicy())
    assert len({item.workspace_id for item in (first, second, foreign, legacy)}) == 4
    assert len({item.ref for item in (first, second, foreign, legacy)}) == 4
    assert registry.count() == 4


@pytest.mark.parametrize("changed", ["policy", "deadline"])
async def test_replay_cannot_change_policy_or_deadline(changed):
    fake = driver()
    registry = WorkspaceRegistry(fake)
    intent = allocation()
    policy = WorkspacePolicy()
    item, _ = await registry.create("owner", policy, allocation=intent)
    requested = (
        replace(intent, expires_at=intent.expires_at + 10) if changed == "deadline" else intent
    )
    new_policy = replace(policy, network="fixture-other") if changed == "policy" else policy
    with pytest.raises(AllocationConflict):
        await registry.create("owner", new_policy, allocation=requested)
    assert item.policy == policy and item.expires_at == intent.expires_at
    fake.create.assert_awaited_once()


async def test_lost_ack_lookup_recovers_credentials_without_any_driver_operation():
    fake = driver()
    registry = WorkspaceRegistry(fake)
    intent = allocation()
    item, _ = await registry.create("owner", WorkspacePolicy(), allocation=intent)
    fake.create.reset_mock()
    fake.verify_isolation.reset_mock()
    fake.list_managed.reset_mock()
    recovered = registry.lookup_allocation("owner", intent)
    assert recovered is item
    verify(registry.allocation_token(recovered, "owner"), item.workspace_id, "owner")
    assert registry.lookup_allocation("other-owner", intent) is None
    fake.create.assert_not_awaited()
    fake.verify_isolation.assert_not_awaited()
    fake.list_managed.assert_not_awaited()


async def test_restart_recovers_the_same_allocation_from_existing_signed_manifest():
    fake = driver()
    intent = allocation()
    original, _ = await WorkspaceRegistry(fake).create(
        "owner", WorkspacePolicy(), allocation=intent
    )
    fresh = WorkspaceRegistry(fake)
    assert await fresh.reconcile() == 1
    recovered = fresh.lookup_allocation("owner", intent)
    assert recovered.workspace_id == original.workspace_id
    assert recovered.ref == original.ref and recovered.recovered
    assert recovered.expires_at == intent.expires_at
    replayed, token = await fresh.create("owner", WorkspacePolicy(), allocation=intent)
    assert replayed is recovered
    verify(token, original.workspace_id, "owner")
    fake.create.assert_awaited_once()


async def test_ambiguous_create_keeps_capacity_and_prohibits_another_dispatch():
    fake = driver()
    fake.create.side_effect = ContainerCreationUncertain
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    intent = allocation()
    with pytest.raises(ContainerCreationUncertain):
        await registry.create("owner", WorkspacePolicy(), allocation=intent)
    with pytest.raises(AllocationPending):
        await registry.create("owner", WorkspacePolicy(), allocation=intent)
    with pytest.raises(AllocationPending):
        registry.lookup_allocation("owner", intent)
    assert registry.count() == 1
    fake.create.assert_awaited_once()


async def test_expired_intent_never_recreates_a_new_empty_workspace(monkeypatch):
    fake = driver()
    registry = WorkspaceRegistry(fake)
    intent = allocation()
    await registry.create("owner", WorkspacePolicy(), allocation=intent)
    monkeypatch.setattr(time, "time", lambda: intent.expires_at + 1)
    with pytest.raises(AllocationExpired):
        await registry.create("owner", WorkspacePolicy(), allocation=intent)
    with pytest.raises(AllocationExpired):
        registry.lookup_allocation("owner", intent)
    fake.create.assert_awaited_once()


async def test_deadline_expiring_during_creation_is_cleaned_not_published(monkeypatch):
    fake = driver()
    intent = allocation()

    async def late_verify(*_):
        monkeypatch.setattr(time, "time", lambda: intent.expires_at + 1)

    fake.verify_isolation.side_effect = late_verify
    registry = WorkspaceRegistry(fake)
    with pytest.raises(AllocationExpired):
        await registry.create("owner", WorkspacePolicy(), allocation=intent)
    assert not registry._items
    fake.destroy.assert_awaited_once()


async def test_excessive_deadline_is_rejected_before_capacity_or_driver():
    fake = driver()
    registry = WorkspaceRegistry(fake)
    intent = WorkspaceAllocation(uuid4(), int(time.time() + HARD_TTL_SEC + 60))
    with pytest.raises(ValueError, match="invalid_allocation_deadline"):
        await registry.create("owner", WorkspacePolicy(), allocation=intent)
    assert registry.count() == 0
    fake.create.assert_not_awaited()
