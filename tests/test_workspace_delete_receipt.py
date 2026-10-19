"""No false delete ACK or false absence while an owned cleanup debt exists."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from application.lifecycle import WorkspaceRegistry
from domain.ownership import mint
from domain.policy import WorkspacePolicy
from presentation import http as http_app
from presentation import workspace_routes

from drivers.base import ContainerRef, DriverError
from drivers.container_cleanup import destroy_known_container


@pytest.fixture
async def deletion_http(monkeypatch):
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "delete-receipt-fixture-not-deployment-key")
    monkeypatch.setattr(workspace_routes, "SERVICE_KEY", "delete-service-fixture")
    driver = SimpleNamespace(
        name="fixture",
        create=AsyncMock(return_value=ContainerRef("fixture", "owned")),
        verify_isolation=AsyncMock(),
        destroy=AsyncMock(),
    )
    registry = WorkspaceRegistry(driver, max_workspaces=1)
    item, token = await registry.create("owner", WorkspacePolicy())
    monkeypatch.setattr(workspace_routes, "registry", registry)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app.app),
        base_url="http://fixture",
        headers={"Authorization": "Bearer delete-service-fixture"},
    ) as client:
        yield client, driver, registry, item, token


async def remove(client, item, token, *, user="owner"):
    return await client.request(
        "DELETE", f"/workspaces/{item.workspace_id}", json={"user_id": user, "token": token}
    )


def ready_retry(registry, key):
    ref, reason, attempts, _ = registry._pending_cleanup[key]
    registry._pending_cleanup[key] = (ref, reason, attempts, 0)


async def test_delete_failure_and_retry_never_claim_absence_until_exact_cleanup_ack(deletion_http):
    client, driver, registry, item, token = deletion_http
    driver.destroy.side_effect = RuntimeError("PRIVATE-DRIVER-MARKER")
    for _ in range(2):
        response = await remove(client, item, token)
        assert response.status_code == 409
        assert response.json()["error"] == "workspace_cleanup_pending"
        assert "PRIVATE" not in response.text
        assert registry.count() == 1 and registry.health()["pending_cleanup"] == 1
    assert item.workspace_id not in registry._items
    driver.destroy.side_effect = None
    ready_retry(registry, item.workspace_id)
    response = await remove(client, item, token)
    assert response.status_code == 200 and response.json() == {"deleted": item.workspace_id}
    assert registry.count() == 0
    assert (await remove(client, item, token)).status_code == 404
    assert all(call.args == (item.ref,) for call in driver.destroy.await_args_list)


async def test_pending_cleanup_does_not_bypass_service_or_owner_auth(deletion_http):
    client, driver, registry, item, token = deletion_http
    driver.destroy.side_effect = RuntimeError("PRIVATE")
    assert (await remove(client, item, token)).status_code == 409
    before = driver.destroy.await_count
    for user, value in (("other", token), ("owner", "bad"), ("other", mint("different", "other"))):
        assert (await remove(client, item, value, user=user)).status_code == 403
    response = await client.request(
        "DELETE",
        f"/workspaces/{item.workspace_id}",
        json={"user_id": "owner", "token": token},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401
    assert driver.destroy.await_count == before and registry.count() == 1


async def test_recovery_pending_workspace_can_be_deleted_without_re_adoption(deletion_http):
    client, driver, registry, item, token = deletion_http
    registry._items.pop(item.workspace_id)
    registry._recovery_pending[item.workspace_id] = item
    response = await remove(client, item, token)
    assert response.status_code == 200
    driver.destroy.assert_awaited_once_with(item.ref)
    assert registry.count() == 0 and not registry._items


@pytest.mark.parametrize("phase", ["reserved", "uncertain"])
async def test_uncertain_creation_never_becomes_a_false_missing_receipt(deletion_http, phase):
    client, driver, registry, item, token = deletion_http
    registry._items.pop(item.workspace_id)
    if phase == "reserved":
        registry._reserved.add(item.workspace_id)
    else:
        registry._uncertain_creates[item.workspace_id] = (time.time() + 60, "fixture")
    assert (await remove(client, item, token)).status_code == 409
    driver.destroy.assert_not_awaited()


async def test_cancellation_preserves_retryable_debt_and_never_returns_delete_ack(deletion_http):
    client, driver, registry, item, token = deletion_http
    entered = asyncio.Event()

    async def waiting(_):
        entered.set()
        await asyncio.Event().wait()

    driver.destroy.side_effect = waiting
    request = asyncio.create_task(remove(client, item, token))
    await asyncio.wait_for(entered.wait(), 1)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert registry.count() == 1
    driver.destroy.side_effect = None
    assert (await remove(client, item, token)).status_code == 200


@pytest.mark.parametrize("code,output", [(1, ""), (0, '"' + "a" * 64 + '"\n'), (0, "PRIVATE")])
async def test_failed_delete_needs_successful_empty_exact_inventory(code, output):
    run = AsyncMock(side_effect=[(1, "", "PRIVATE"), (code, output, "PRIVATE")])
    with pytest.raises(DriverError, match="^docker destroy failed$"):
        await destroy_known_container(ContainerRef("docker", "a" * 64), run)


async def test_lost_delete_ack_is_settled_by_exact_native_id_inventory():
    run = AsyncMock(side_effect=[(1, "", "PRIVATE"), (0, "", "")])
    await destroy_known_container(ContainerRef("docker", "a" * 64), run)
    assert run.await_args.args == (
        "ps",
        "--all",
        "--no-trunc",
        "--filter",
        "id=" + "a" * 64,
        "--format",
        "{{json .ID}}",
    )


@pytest.mark.parametrize("identity", ["", "a", "gpthub-ws-fixture"])
async def test_unknown_or_mutable_identity_is_not_absence_proof(identity):
    run = AsyncMock(return_value=(1, "", "PRIVATE"))
    with pytest.raises(DriverError):
        await destroy_known_container(ContainerRef("docker", identity), run)
    assert run.await_count == 1
