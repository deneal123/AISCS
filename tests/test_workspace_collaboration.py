"""Deterministic contract tests for S19's Redis-only room state."""

from __future__ import annotations

import json

import pytest

from service.services.chat.application import workspace_collaboration as collaboration
from service.services.chat.presentation.routers import workspace_coordination
from service.services.chat.presentation.routers.chat_api.workspace_api import (
    _request_active_run_cancellation,
    _ui_capability,
)


class FakeRedis:
    """Small async Redis subset; values intentionally remain inspectable in tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.counter: dict[str, int] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key):
        return self.values.get(str(key))

    async def set(self, key, value, *, ex=None, nx=False):
        key = str(key)
        if nx and key in self.values:
            return False
        self.values[key] = value.decode() if isinstance(value, bytes) else str(value)
        return True

    async def expire(self, key, seconds):
        return key in self.values or key in self.lists

    async def incr(self, key):
        key = str(key)
        self.counter[key] = self.counter.get(key, 0) + 1
        return self.counter[key]

    async def delete(self, key):
        return int(self.values.pop(str(key), None) is not None)

    async def lpush(self, key, value):
        self.lists.setdefault(str(key), []).insert(0, str(value))
        return len(self.lists[str(key)])

    async def ltrim(self, key, start, end):
        self.lists[str(key)] = self.lists.get(str(key), [])[int(start) : int(end) + 1]

    async def lrange(self, key, start, end):
        values = self.lists.get(str(key), [])
        return values[int(start) : None if int(end) == -1 else int(end) + 1]

    async def publish(self, channel, payload):
        self.published.append((str(channel), str(payload)))
        return 1

    async def scan(self, cursor=0, match="*", count=10):
        prefix = str(match).rstrip("*")
        return 0, [key for key in self.values if key.startswith(prefix)][: int(count)]


@pytest.fixture(autouse=True)
def coordination_secret(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "tests-only-coordination-secret")


def _cap(role: str = "ui", *, actor: str = "owner", run_id: str = "run") -> str:
    return collaboration.mint_capability(
        "workspace-opaque", role=role, actor_seed=actor, run_id=run_id, expires_at=4_102_444_800
    )


@pytest.mark.asyncio
async def test_capability_is_signed_opaque_and_binds_role() -> None:
    value = _cap("agent", actor="actual-user-id", run_id="current-run-id")

    assert "actual-user-id" not in value and "current-run-id" not in value
    parsed = collaboration.verify_capability(value, required_role="agent")
    assert parsed.workspace_id == "workspace-opaque"
    with pytest.raises(collaboration.CollaborationForbidden):
        collaboration.verify_capability(value, required_role="ui")


def test_ui_capability_separates_opaque_browser_sessions() -> None:
    ref = {"workspace_id": "workspace-opaque", "expires_at": 4_102_444_800}
    first = collaboration.verify_capability(
        _ui_capability(ref, "user-opaque", "11111111-1111-4111-8111-111111111111")
    )
    same_tab = collaboration.verify_capability(
        _ui_capability(ref, "user-opaque", "11111111-1111-4111-8111-111111111111")
    )
    second = collaboration.verify_capability(
        _ui_capability(ref, "user-opaque", "22222222-2222-4222-8222-222222222222")
    )

    assert first.actor_id == same_tab.actor_id
    assert first.actor_id != second.actor_id
    assert "user-opaque" not in first.actor_id


@pytest.mark.asyncio
async def test_lease_fencing_and_ttl_bound_room_snapshot() -> None:
    redis = FakeRedis()
    store = collaboration.WorkspaceCollaborationStore(
        redis, workspace_id="workspace-opaque", expires_at=4_102_444_800
    )
    owner = collaboration.verify_capability(_cap("ui", actor="owner"))
    agent = collaboration.verify_capability(_cap("agent", actor="agent"), required_role="agent")

    lease = await store.acquire_lease(owner, "src/main.py")
    assert lease.fence == 1 and lease.public()["holder"] == "you"
    with pytest.raises(collaboration.CollaborationConflict):
        await store.acquire_lease(agent, "src/main.py")
    assert await store.release_lease(owner, "src/main.py", lease.fence)
    successor = await store.acquire_lease(agent, "src/main.py")
    assert successor.fence == 2

    snapshot = await store.snapshot(revision="revision")
    assert snapshot["revision"] == "revision"
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "actual-user-id" not in serialized and "src/main.py" in serialized


@pytest.mark.asyncio
async def test_pause_and_cancel_are_idempotent_safe_boundaries() -> None:
    redis = FakeRedis()
    store = collaboration.WorkspaceCollaborationStore(
        redis, workspace_id="workspace-opaque", expires_at=4_102_444_800
    )
    agent = collaboration.verify_capability(_cap("agent"), required_role="agent")

    assert (await store.set_control("pause"))["state"] == "pause_requested"
    with pytest.raises(collaboration.CollaborationPaused):
        await store.agent_safe_boundary(agent)
    assert (await store.control_state())["state"] == "paused"
    assert (await store.set_control("resume"))["state"] == "running"
    assert (await store.agent_safe_boundary(agent))["state"] == "running"
    assert (await store.set_control("cancel"))["state"] == "cancelled"
    assert (await store.set_control("cancel"))["state"] == "cancelled"
    with pytest.raises(collaboration.CollaborationCancelled):
        await store.agent_safe_boundary(agent)


@pytest.mark.asyncio
async def test_active_agent_run_is_private_and_can_be_cleared() -> None:
    redis = FakeRedis()
    store = collaboration.WorkspaceCollaborationStore(
        redis, workspace_id="workspace-opaque", expires_at=4_102_444_800
    )

    await store.register_agent_run("celery-private-task")
    assert await store.active_agent_run() == "celery-private-task"
    snapshot = await store.snapshot()
    assert "celery-private-task" not in json.dumps(snapshot)
    await store.clear_agent_run("different-task")
    assert await store.active_agent_run() == "celery-private-task"
    await store.clear_agent_run("celery-private-task")
    assert await store.active_agent_run() == ""


@pytest.mark.asyncio
async def test_room_cancel_uses_existing_cooperative_worker_flag() -> None:
    redis = FakeRedis()
    store = collaboration.WorkspaceCollaborationStore(
        redis, workspace_id="workspace-opaque", expires_at=4_102_444_800
    )
    await store.register_agent_run("celery-private-task")

    await _request_active_run_cancellation(store, redis)

    assert redis.values["chat:cancel:celery-private-task"] == "1"
    assert "celery-private-task" not in json.dumps(await store.snapshot())


@pytest.mark.asyncio
async def test_issues_are_redis_only_and_agent_cannot_create_them() -> None:
    redis = FakeRedis()
    store = collaboration.WorkspaceCollaborationStore(
        redis, workspace_id="workspace-opaque", expires_at=4_102_444_800
    )
    owner = collaboration.verify_capability(_cap("ui", actor="owner"))
    agent = collaboration.verify_capability(_cap("agent", actor="agent"), required_role="agent")

    issue = await store.create_issue(
        owner,
        path="src/main.py",
        start_line=3,
        end_line=5,
        revision="abc",
        title="Fix",
        body="private issue text",
    )
    assert (await store.list_issues())[0]["body"] == "private issue text"
    with pytest.raises(collaboration.CollaborationForbidden):
        await store.create_issue(
            agent, path="x.py", start_line=1, end_line=1, revision="", title="No", body=""
        )
    resolved = await store.update_issue(agent, issue["issue_id"], status="resolved")
    assert resolved["status"] == "resolved"
    assert await store.list_issues() == []


def test_internal_signature_is_body_and_path_bound() -> None:
    body = b'{"capability":"opaque"}'
    headers = collaboration.signed_internal_request(
        "POST", "/internal/workspace-coordination/preflight", body
    )
    collaboration.verify_internal_request(
        "POST",
        "/internal/workspace-coordination/preflight",
        body,
        headers["X-Workspace-Timestamp"],
        headers["X-Workspace-Signature"],
    )
    with pytest.raises(collaboration.CollaborationForbidden):
        collaboration.verify_internal_request(
            "POST",
            "/internal/workspace-coordination/boundary",
            body,
            headers["X-Workspace-Timestamp"],
            headers["X-Workspace-Signature"],
        )


def test_capability_cannot_be_replayed_against_another_workspace_route() -> None:
    capability = collaboration.verify_capability(_cap("agent"), required_role="agent")

    assert workspace_coordination._capability_matches_route(capability, "workspace-opaque")
    assert not workspace_coordination._capability_matches_route(capability, "other-workspace")
