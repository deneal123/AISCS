"""Invalid policy is rejected before capacity reservation or Docker side effects."""

from unittest.mock import AsyncMock

import pytest
from application.lifecycle import WorkspaceRegistry
from domain.policy import WorkspacePolicy, policy_from_request

from drivers.base import ContainerRef


@pytest.fixture(autouse=True)
def owner_secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "fixture-owner-key-not-a-deployment-secret")


@pytest.mark.parametrize(
    "field,value",
    [
        (field, value)
        for field in ("memory_bytes", "pids_limit", "quota_bytes", "max_output_chars")
        for value in (0, -1, True, "128", 1.5)
    ]
    + [("cpus", value) for value in (0, -1, True, "1", float("nan"), float("inf"), 1e-12)]
    + [("exec_timeout_sec", value) for value in (True, "30", float("nan"), float("inf"))]
    + [("read_only_root", value) for value in ("false", 0, None)]
    + [("cpus", 10**400), ("exec_timeout_sec", 10**400), ("root", "//workspace")]
    + [(field, "x" * 4097) for field in ("image", "network", "user")]
    + [
        ("root", value)
        for value in (
            "/",
            "/workspace/../etc",
            "/workspace/",
            "/workspace//files",
            "/private\nmarker",
        )
    ]
    + [
        (field, value)
        for field in ("image", "network", "user")
        for value in ("", "--private-marker", "private\nmarker")
    ],
)
async def test_invalid_input_is_rejected_before_driver_invocation(field, value):
    driver = type(
        "Driver",
        (),
        {
            "create": AsyncMock(return_value=ContainerRef("fixture", "owned-fixture")),
            "verify_isolation": AsyncMock(),
            "destroy": AsyncMock(),
        },
    )()
    registry = WorkspaceRegistry(driver)
    with pytest.raises(ValueError) as error:
        policy = WorkspacePolicy(**{field: value})
        await registry.create("owner", policy)
    assert "private" not in str(error.value)
    driver.create.assert_not_awaited()
    driver.destroy.assert_not_awaited()
    assert registry.count() == 0


def test_valid_non_default_policy_preserves_explicit_values():
    policy = policy_from_request({"memory_bytes": 268435456, "cpus": 0.5, "root": "/project"})
    assert policy.memory_bytes == 268435456
    assert policy.cpus == 0.5
    assert policy.root == "/project"
