import json
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.services.chat.domain.ide.runtime import RuntimeAttempt

pytestmark = pytest.mark.asyncio


def settings(**kwargs):
    return SimpleNamespace(
        workspace_enabled=True,
        workspace_url="http://workspace.test",
        workspace_api_key="PRIVATE_KEY",
        workspace_timeout_sec=10,
        workspace_ttl_sec=1800,
        **kwargs,
    )


def attempt():
    return RuntimeAttempt(uuid4(), int(time.time()) + 600, "dispatching", 1)


def binding(value):
    return {
        "workspace_id": "a" * 32,
        "token": f"{value.expires_at}." + "b" * 64,
        "root": "/workspace",
        "expires_at": value.expires_at,
        "policy": {"network": "none", "read_only_root": True},
    }


async def test_preflight_requires_explicit_protocol_before_any_allocation():
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer PRIVATE_KEY"
        return httpx.Response(
            200,
            json={
                "service": "workspace",
                "contract": {"allocation_protocol": 1, "allocation_max_ttl_sec": 300},
            },
        )

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    assert await client.allocation_ttl() == 300
    assert calls == [("GET", "/health")]


@pytest.mark.parametrize(
    "contract",
    [
        {},
        {"allocation_protocol": True},
        {"allocation_protocol": 1, "allocation_max_ttl_sec": True},
        {"allocation_protocol": 1, "allocation_max_ttl_sec": -1},
    ],
)
async def test_old_or_malformed_capability_is_not_support(contract):
    client = IdeWorkspaceClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"service": "workspace", "contract": contract})
        ),
    )
    assert await client.allocation_ttl() is None


async def test_create_uses_dedicated_endpoint_and_fixed_scope_without_legacy_fallback():
    value = attempt()
    calls = []

    def handle(request):
        calls.append(request.url.path)
        assert json.loads(request.content) == {
            "user_id": str(owner),
            "allocation": {
                "allocation_id": str(value.allocation_id),
                "expires_at": value.expires_at,
            },
        }
        return httpx.Response(200, json=binding(value))

    owner = uuid4()
    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    result = await client.observe(owner, value, create=True)
    assert result.state == "ready"
    assert "PRIVATE" not in repr(result) and "bbbb" not in repr(result.binding)
    assert (await client.observe(owner, value)).state == "ready"
    assert calls == ["/workspaces/allocations", "/workspaces/allocations/lookup"]


async def test_pdf_creation_initializes_history_on_the_same_allocation_but_replay_only_looks_up():
    value, owner = attempt(), uuid4()
    calls = []

    def handle(request):
        calls.append(request.url.path)
        assert json.loads(request.content) == {
            "user_id": str(owner),
            "allocation": {
                "allocation_id": str(value.allocation_id),
                "expires_at": value.expires_at,
            },
        }
        return httpx.Response(200, json={**binding(value), "versioned": True})

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(handle))
    assert (
        await client.observe(owner, value, create=True, initialize_history=True)
    ).state == "ready"
    assert (await client.observe(owner, value, initialize_history=True)).state == "ready"
    assert calls == ["/workspaces", "/workspaces/allocations/lookup"]


@pytest.mark.parametrize("versioned", [False, None, 1, "true"])
async def test_pdf_creation_never_claims_history_is_ready_from_an_unconfirmed_ack(versioned):
    value = attempt()
    client = IdeWorkspaceClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={**binding(value), "versioned": versioned})
        ),
    )
    assert (
        await client.observe(uuid4(), value, create=True, initialize_history=True)
    ).state == "unavailable"


@pytest.mark.parametrize(
    "code,state,retry",
    [
        ("workspace_allocation_pending", "pending", False),
        ("workspace_allocation_expired", "expired", False),
        ("workspace_allocation_conflict", "rejected", False),
        ("workspace_not_found", "unknown", False),
        ("quota_exceeded", "rejected", True),
        ("PRIVATE_ERROR_BODY", "unavailable", False),
    ],
)
async def test_only_closed_errors_are_projected_without_remote_details(code, state, retry, caplog):
    client = IdeWorkspaceClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(409, json={"error": code, "detail": "PRIVATE_REMOTE_PAYLOAD"})
        ),
    )
    result = await client.observe(uuid4(), attempt(), create=True)
    assert result.state == state and result.retry_allowed is retry
    assert "PRIVATE" not in repr(result) and "PRIVATE" not in caplog.text


async def test_lookup_quota_or_transport_failure_never_rearms_creation():
    calls = []

    def fail(request):
        calls.append(request.url.path)
        raise httpx.ConnectError("PRIVATE_TRANSPORT", request=request)

    client = IdeWorkspaceClient(settings(), transport=httpx.MockTransport(fail))
    result = await client.observe(uuid4(), attempt(), create=True)
    assert result.state == "unavailable" and not result.retry_allowed
    assert len(calls) == 1
    client = IdeWorkspaceClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(413, json={"error": "quota_exceeded"})
        ),
    )
    assert not (await client.observe(uuid4(), attempt())).retry_allowed


@pytest.mark.parametrize(
    "change",
    [
        {"workspace_id": "a" * 16},
        {"token": "PRIVATE_TOKEN"},
        {"expires_at": True},
        {"root": "/private"},
        {"policy": {"network": "bridge"}},
    ],
)
async def test_invalid_binding_cannot_become_ready(change):
    value = attempt()
    client = IdeWorkspaceClient(
        settings(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={**binding(value), **change})
        ),
    )
    result = await client.observe(uuid4(), value, create=True)
    assert result.state == "unavailable" and result.binding is None


async def test_expired_generation_does_not_contact_sidecar():
    transport = httpx.MockTransport(lambda _: pytest.fail("expired allocation contacted sidecar"))
    client = IdeWorkspaceClient(settings(), transport=transport)
    assert (await client.observe(uuid4(), replace(attempt(), expires_at=1))).state == "expired"
