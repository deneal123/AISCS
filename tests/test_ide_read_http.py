import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from application.allocations import WorkspaceAllocation
from application.lifecycle import WorkspaceRegistry
from domain.policy import WorkspacePolicy
from presentation import http as http_app
from presentation import workspace_routes
from test_workspace_allocations import driver


@pytest.fixture
async def read_http(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "ide-read-fixture-not-a-deployment-key")
    monkeypatch.setattr(workspace_routes, "SERVICE_KEY", "ide-read-fixture")
    fake = driver()
    fake.exec = AsyncMock(
        return_value=SimpleNamespace(
            stdout='{"entries":[],"truncated":false}', exit_code=0, truncated=False
        )
    )
    fake.exec_with_input = fake.exec
    registry = WorkspaceRegistry(fake)
    monkeypatch.setattr(workspace_routes, "registry", registry)
    item, _ = await registry.create(
        "owner", WorkspacePolicy(), allocation=WorkspaceAllocation(uuid4(), int(time.time()) + 600)
    )
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app.app),
        base_url="http://ide-read-fixture",
        headers={"Authorization": "Bearer ide-read-fixture"},
    )
    payload = {"user_id": "owner", "token": registry.allocation_token(item, "owner"), "path": ""}
    return client, fake, registry, item, payload


async def test_private_read_requires_service_key_owner_and_capability(read_http):
    client, fake, _, item, payload = read_http
    async with client:
        path = f"/workspaces/{item.workspace_id}/ide/tree"
        assert (
            await client.post(path, json=payload, headers={"Authorization": "Bearer wrong"})
        ).status_code == 401
        assert (await client.post(path, json={**payload, "user_id": "other"})).status_code == 403
        assert (await client.post(path, json={**payload, "token": "wrong"})).status_code == 403
    fake.exec.assert_not_awaited()


async def test_read_is_bounded_stdin_only_and_never_snapshots_or_reallocates(read_http):
    client, fake, registry, item, payload = read_http
    async with client:
        response = await client.post(f"/workspaces/{item.workspace_id}/ide/tree", json=payload)
    assert response.status_code == 200 and response.json() == {"entries": [], "truncated": False}
    fake.create.assert_awaited_once()
    fake.exec.assert_awaited_once()
    assert registry.count() == 1
    assert json.loads(fake.exec.await_args.kwargs["payload"])["path"] == ""


async def test_paths_and_payload_cannot_override_root_or_execute(read_http):
    client, fake, _, item, payload = read_http
    async with client:
        path = f"/workspaces/{item.workspace_id}/ide/tree"
        assert (await client.post(path, json={**payload, "root": "/"})).status_code == 422
        assert (await client.post(path, json={**payload, "path": "../secret"})).status_code == 403
    fake.exec.assert_not_awaited()
