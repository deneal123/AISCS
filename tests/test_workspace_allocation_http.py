import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from application.lifecycle import WorkspaceRegistry
from presentation import http as http_app
from presentation import workspace_routes
from test_workspace_allocations import driver


@pytest.fixture
def allocation_http(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "allocation-http-fixture-not-a-deployment-key")
    monkeypatch.setattr(workspace_routes, "SERVICE_KEY", "allocation-service-fixture")
    fake = driver()
    fake.exec = AsyncMock(return_value=SimpleNamespace(stdout="__OK__"))
    registry = WorkspaceRegistry(fake)
    monkeypatch.setattr(workspace_routes, "registry", registry)
    payload = {
        "user_id": "owner",
        "allocation": {"allocation_id": str(uuid4()), "expires_at": int(time.time()) + 600},
    }
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app.app),
        base_url="http://workspace-fixture",
        headers={"Authorization": "Bearer allocation-service-fixture"},
    )
    return client, fake, registry, payload


async def test_lookup_before_and_after_create_is_passive_and_owned(allocation_http):
    client, fake, registry, payload = allocation_http
    async with client:
        absent = await client.post("/workspaces/allocations/lookup", json=payload)
        assert absent.status_code == 404 and registry.count() == 0
        fake.create.assert_not_awaited()
        created = await client.post("/workspaces", json=payload)
        assert created.status_code == 200 and created.json()["versioned"]
        fake.exec.reset_mock()
        recovered = await client.post("/workspaces/allocations/lookup", json=payload)
        assert recovered.status_code == 200
        assert recovered.json()["workspace_id"] == created.json()["workspace_id"]
        assert recovered.json()["expires_at"] == payload["allocation"]["expires_at"]
        foreign = await client.post(
            "/workspaces/allocations/lookup",
            json={
                **payload,
                "user_id": "other-owner",
            },
        )
        assert foreign.status_code == 404
        fake.create.assert_awaited_once()
        fake.exec.assert_not_awaited()


async def test_service_auth_is_required_before_lookup(allocation_http):
    client, fake, registry, payload = allocation_http
    async with client:
        response = await client.post(
            "/workspaces/allocations/lookup",
            json=payload,
            headers={"Authorization": "Bearer wrong-fixture"},
        )
    assert response.status_code == 401 and response.json()["error"] == "unauthorized"
    fake.create.assert_not_awaited()
    assert registry.count() == 0


async def test_restart_lookup_and_replay_keep_canonical_integer_deadline(
    allocation_http, monkeypatch
):
    client, fake, registry, payload = allocation_http
    async with client:
        created = await client.post("/workspaces/allocations", json=payload)
        assert created.status_code == 200
        fresh = WorkspaceRegistry(fake)
        assert await fresh.reconcile() == 1
        monkeypatch.setattr(workspace_routes, "registry", fresh)
        for path in ("/workspaces/allocations/lookup", "/workspaces/allocations"):
            recovered = await client.post(path, json=payload)
            assert recovered.status_code == 200
            assert recovered.json()["workspace_id"] == created.json()["workspace_id"]
            assert type(recovered.json()["expires_at"]) is int
            assert recovered.json()["expires_at"] == payload["allocation"]["expires_at"]
    fake.create.assert_awaited_once()
    fake.exec.assert_not_awaited()


async def test_inflight_replay_and_lookup_expose_pending_without_dispatch(allocation_http):
    client, fake, registry, payload = allocation_http
    entered, release = asyncio.Event(), asyncio.Event()
    original = fake.create.side_effect

    async def slow(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    fake.create.side_effect = slow
    async with client:
        request = asyncio.create_task(client.post("/workspaces", json=payload))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            for path in ("/workspaces", "/workspaces/allocations/lookup"):
                response = await client.post(path, json=payload)
                assert response.status_code == 409
                assert response.json()["error"] == "workspace_allocation_pending"
            fake.create.assert_awaited_once()
            assert registry.count() == 1
        finally:
            release.set()
            assert (await request).status_code == 200


@pytest.mark.parametrize(
    "change",
    [
        {"expires_at": True},
        {"expires_at": 1.5},
        {"allocation_id": "PRIVATE_INVALID_UUID"},
        {"root": "PRIVATE_PATH"},
    ],
)
async def test_invalid_allocation_shape_is_private_and_non_mutating(allocation_http, change):
    client, fake, registry, payload = allocation_http
    payload["allocation"].update(change)
    async with client:
        for path in ("/workspaces", "/workspaces/allocations/lookup"):
            response = await client.post(path, json=payload)
            assert response.status_code == 422
            assert response.json()["error"] == "invalid_request"
            assert "PRIVATE" not in response.text
    fake.create.assert_not_awaited()
    assert registry.count() == 0


async def test_expired_allocation_is_not_silently_recreated(allocation_http):
    client, fake, registry, payload = allocation_http
    payload["allocation"]["expires_at"] = int(time.time()) - 10
    async with client:
        for path in ("/workspaces", "/workspaces/allocations/lookup"):
            response = await client.post(path, json=payload)
            assert response.status_code == 410
            assert response.json()["error"] == "workspace_allocation_expired"
    fake.create.assert_not_awaited()
    assert registry.count() == 0


async def test_dedicated_protocol_is_required_and_does_not_initialize_legacy_git(allocation_http):
    client, fake, registry, payload = allocation_http
    async with client:
        invalid = await client.post("/workspaces/allocations", json={"user_id": "owner"})
        assert invalid.status_code == 422 and registry.count() == 0
        response = await client.post("/workspaces/allocations", json=payload)
        assert response.status_code == 200
        assert response.json()["versioned"] is False
    fake.exec.assert_not_awaited()
    fake.create.assert_awaited_once()


async def test_health_advertises_static_allocation_protocol_without_provisioning(allocation_http):
    client, fake, registry, _ = allocation_http
    async with client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["contract"]["allocation_protocol"] == 1
    assert response.json()["contract"]["allocation_max_ttl_sec"] > 0
    fake.create.assert_not_awaited()
    assert registry.count() == 0
