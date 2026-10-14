"""Signature compatibility must never retry an operation that has already started."""

from unittest.mock import AsyncMock

import pytest
from domain.policy import WorkspacePolicy
from infrastructure.container_operations import ContainerOperations

from drivers.base import ContainerRef, DriverError


async def test_internal_type_error_is_not_a_legacy_signature_signal():
    invocation = AsyncMock(side_effect=TypeError("private-internal-create-body"))
    driver = type("Driver", (), {"create": invocation})()
    operations = ContainerOperations(driver)
    with pytest.raises(TypeError):
        await operations.create("fixture", WorkspacePolicy(), {"managed": "fixture"})
    invocation.assert_awaited_once()
    assert invocation.await_args.kwargs == {"labels": {"managed": "fixture"}}


@pytest.mark.parametrize("legacy", [False, True])
async def test_compatible_signature_is_selected_before_single_invocation(legacy):
    calls = []
    ref = ContainerRef("fixture", "owned-fixture")

    class Driver:
        async def create(self, workspace_id, policy, *, labels):
            calls.append((workspace_id, policy, labels))
            return ref

    class LegacyDriver:
        async def create(self, workspace_id, policy):
            calls.append((workspace_id, policy, None))
            return ref

    operations = ContainerOperations(LegacyDriver() if legacy else Driver())
    policy = WorkspacePolicy()
    labels = {"managed": "fixture"}
    assert await operations.create("fixture", policy, labels) == ref
    assert calls == [("fixture", policy, None if legacy else labels)]


async def test_unsupported_signature_fails_without_calling_driver():
    calls = []

    class Driver:
        async def create(self, workspace_id, policy, required_private_arg):
            calls.append(workspace_id)

    with pytest.raises(DriverError, match="driver create signature invalid"):
        await ContainerOperations(Driver()).create("fixture", WorkspacePolicy(), {})
    assert calls == []


async def test_uninspectable_signature_fails_closed_without_execution(monkeypatch):
    import inspect

    invocation = AsyncMock()
    driver = type("Driver", (), {"create": invocation})()

    def unsupported(_callable):
        raise ValueError("private-signature-body")

    monkeypatch.setattr(inspect, "signature", unsupported)
    with pytest.raises(DriverError, match="driver create signature unavailable"):
        await ContainerOperations(driver).create("fixture", WorkspacePolicy(), {})
    invocation.assert_not_awaited()
