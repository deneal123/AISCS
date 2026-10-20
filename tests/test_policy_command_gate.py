"""The final command gate runs inside the existing non-reentrant policy lock."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from application.lifecycle import Workspace, WorkspaceRegistry
from domain.policy import WorkspacePolicy

from drivers.base import ContainerRef


async def test_policy_gate_is_locked_and_denial_neither_mutates_nor_deadlocks():
    registry = WorkspaceRegistry(AsyncMock())
    original = WorkspacePolicy()
    item = Workspace("fixture", ContainerRef("fixture", "container"), original, time.time() + 60)

    async def deny():
        assert item.operation_lock.locked()
        raise RuntimeError("command_busy")

    with pytest.raises(RuntimeError, match="command_busy"):
        await asyncio.wait_for(registry.update_policy(item, {}, before_update=deny), timeout=0.5)
    assert item.policy is original and not item.operation_lock.locked()

    async def allow():
        assert item.operation_lock.locked()

    policy = await asyncio.wait_for(
        registry.update_policy(item, {}, before_update=allow), timeout=0.5
    )
    assert policy == original and not item.operation_lock.locked()
