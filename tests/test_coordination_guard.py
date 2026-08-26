"""Fail-closed regression tests for workspace coordination."""

from __future__ import annotations

import pytest
from application import coordination_guard
from infrastructure.coordinator_client import CoordinationError


class _Payload:
    coordination_capability = "capability"
    coordination_fence = 1


async def test_coordinator_outage_is_fail_closed_and_not_a_driver_failure(monkeypatch) -> None:
    async def unavailable(*_args, **_kwargs):
        raise CoordinationError("unavailable")

    monkeypatch.setattr(coordination_guard, "preflight", unavailable)

    with pytest.raises(coordination_guard.GuardFailure) as caught:
        await coordination_guard.require_mutation(_Payload(), "write", path="notes.txt")

    assert caught.value.code == "workspace_unavailable"
    assert caught.value.status == 503
