"""Cancellation must not make owned containers disappear from capacity accounting."""

import asyncio
import time
from unittest.mock import AsyncMock

import application.lifecycle as lifecycle
import pytest
from application.lifecycle import TooManyWorkspaces, WorkspaceRegistry
from domain.policy import WorkspacePolicy

from drivers.base import ContainerRef


@pytest.fixture(autouse=True)
def owner_secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "fixture-owner-key-not-a-deployment-secret")


def driver():
    return type(
        "Driver",
        (),
        {
            "name": "fixture",
            "create": AsyncMock(return_value=ContainerRef("fixture", "owned-container")),
            "verify_isolation": AsyncMock(),
            "destroy": AsyncMock(),
        },
    )()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_cancel_during_isolation_preserves_cleanup_and_releases_reservation(cleanup_fails):
    fake = driver()
    entered = asyncio.Event()

    async def verify(*_):
        entered.set()
        await asyncio.Event().wait()

    fake.verify_isolation.side_effect = verify
    if cleanup_fails:
        fake.destroy.side_effect = RuntimeError("private-cleanup-marker")
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not registry._reserved
    assert not registry._items
    fake.destroy.assert_awaited_once()
    assert registry.count() == int(cleanup_fails)
    assert registry.health()["pending_cleanup"] == int(cleanup_fails)
    if cleanup_fails:
        with pytest.raises(TooManyWorkspaces):
            await registry.create("other", WorkspacePolicy())
        fake.destroy.side_effect = None
        # Advance only this fixture's retry deadline; no wall-clock sleep.
        key, (ref, reason, attempts, _) = next(iter(registry._pending_cleanup.items()))
        registry._pending_cleanup[key] = (ref, reason, attempts, 0)
        assert await registry.reap() == 1
        assert registry.count() == 0


class CancelOnSecondAcquisition(asyncio.Lock):
    """Inject cancellation at the lock boundary following active-state removal."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def __aenter__(self):
        self.calls += 1
        if self.calls == 2:
            raise asyncio.CancelledError
        return await super().__aenter__()


@pytest.mark.parametrize("operation", ["destroy", "reap"])
async def test_retirement_atomically_moves_active_capacity_to_cleanup(operation):
    fake = driver()
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    item, _ = await registry.create("owner", WorkspacePolicy())
    fake.destroy.reset_mock()
    registry._lock = CancelOnSecondAcquisition()
    if operation == "reap":
        item.expires_at = time.time() - 1
    with pytest.raises(asyncio.CancelledError):
        if operation == "destroy":
            await registry.destroy(item.workspace_id)
        else:
            await registry.reap()
    assert not registry._items
    assert registry.count() == 1
    assert registry.health()["pending_cleanup"] == 1
    fake.destroy.assert_not_awaited()
    registry._lock = asyncio.Lock()
    assert await registry.reap() == 1
    fake.destroy.assert_awaited_once_with(item.ref)
    assert registry.count() == 0


@pytest.mark.parametrize("operation", ["create", "destroy", "reap"])
async def test_cancel_during_driver_cleanup_keeps_debt_for_the_next_reap(operation):
    fake = driver()
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    cleanup_entered = asyncio.Event()

    async def blocked_destroy(*_):
        cleanup_entered.set()
        await asyncio.Event().wait()

    if operation == "create":
        fake.verify_isolation.side_effect = RuntimeError("private-isolation-marker")
        fake.destroy.side_effect = blocked_destroy
        task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    else:
        item, _ = await registry.create("owner", WorkspacePolicy())
        fake.destroy.side_effect = blocked_destroy
        if operation == "destroy":
            task = asyncio.create_task(registry.destroy(item.workspace_id))
        else:
            item.expires_at = time.time() - 1
            task = asyncio.create_task(registry.reap())
    await asyncio.wait_for(cleanup_entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not registry._reserved
    assert not registry._items
    assert registry.count() == 1
    fake.destroy.side_effect = None
    assert await registry.reap() == 1
    assert registry.count() == 0


async def test_cancel_after_verification_before_registry_publish_reclaims_container():
    fake = driver()
    registry = WorkspaceRegistry(fake)

    async def verified(*_):
        # Deliver cancellation exactly at the publication lock, not at verify.
        lock = CancelOnSecondAcquisition()
        lock.calls = 1
        registry._lock = lock

    fake.verify_isolation.side_effect = verified
    with pytest.raises(asyncio.CancelledError):
        await registry.create("owner", WorkspacePolicy())
    assert not registry._reserved
    assert not registry._items
    assert registry.count() == 0
    fake.destroy.assert_awaited_once()


@pytest.mark.parametrize("failure", ["owner_binding", "token_mint"])
async def test_post_verification_failure_never_publishes_unissued_workspace(monkeypatch, failure):
    fake = driver()
    registry = WorkspaceRegistry(fake)

    def reject(*_, **__):
        raise RuntimeError("private-post-verification-marker")

    if failure == "owner_binding":
        monkeypatch.setattr(lifecycle, "owner_binding", reject)
    else:
        monkeypatch.setattr(lifecycle.ownership, "mint", reject)
    with pytest.raises(RuntimeError, match="private-post-verification-marker"):
        await registry.create("owner", WorkspacePolicy())
    assert not registry._reserved
    assert not registry._items
    assert registry.count() == 0
    fake.destroy.assert_awaited_once()


@pytest.mark.parametrize("initial_failure", ["cancel", "verification"])
async def test_repeated_cancel_cannot_interrupt_cleanup_handoff(initial_failure):
    fake = driver()
    registry = WorkspaceRegistry(fake)
    entered = asyncio.Event()
    leave_verify = asyncio.Event()

    async def verify(*_):
        entered.set()
        await leave_verify.wait()
        raise RuntimeError("private-verification-marker")

    fake.verify_isolation.side_effect = verify
    task = asyncio.create_task(registry.create("owner", WorkspacePolicy()))
    await asyncio.wait_for(entered.wait(), 1)
    await registry._lock.acquire()
    try:
        if initial_failure == "cancel":
            task.cancel()
        else:
            leave_verify.set()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cleanup handoff must settle before returning cancellation"
    finally:
        registry._lock.release()
        result = (await asyncio.gather(task, return_exceptions=True))[0]
    assert isinstance(result, asyncio.CancelledError)
    assert not registry._reserved
    assert not registry._items
    assert registry.count() == 0
    fake.destroy.assert_awaited_once()


async def test_cancelled_handoff_child_is_terminal_not_a_retry_loop(monkeypatch):
    registry = WorkspaceRegistry(driver())

    async def stopped(*_):
        raise asyncio.CancelledError

    monkeypatch.setattr(registry, "_retire_failed_creation", stopped)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(registry._settle_creation_cleanup("fixture", None), 1)
