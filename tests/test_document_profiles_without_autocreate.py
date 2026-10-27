"""Каталог и явная работа с PDF не разрешают фоновое создание сред."""

import httpx
import pytest

from service.infrastructure import workspace_client as client
from service.settings import config


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(config.agents, "workspace_enabled", True)
    monkeypatch.setattr(config.agents, "workspace_autocreate", False)
    monkeypatch.setattr(config.agents, "workspace_url", "http://workspace.test")
    monkeypatch.setattr(config.agents, "workspace_api_key", "synthetic-key")
    calls = []

    def handle(request):
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer synthetic-key"
        if request.url.path == "/document-profiles":
            return httpx.Response(200, json={"profiles": [{"profile_id": "generic_document"}]})
        return httpx.Response(200, json={"path": "documents/paper", "revision": "confirmed"})

    constructor = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: constructor(transport=httpx.MockTransport(handle), **kwargs),
    )
    return calls


@pytest.mark.asyncio
async def test_catalog_read_works_with_default_no_autocreate_policy(transport):
    result = await client.document_profiles()
    assert result["profiles"] == [{"profile_id": "generic_document"}]
    assert transport == [("GET", "/document-profiles")]


@pytest.mark.asyncio
async def test_explicit_document_operation_uses_existing_binding_without_allocating(transport):
    result = await client.create_document_project(
        {"workspace_id": "owned", "user_id": "owner", "token": "synthetic-owner-token"},
        path="documents/paper",
        profile_id="generic_document",
        mode="draft",
        locale="ru-RU",
        expected_revision="base",
        fence=1,
    )
    assert result == {"path": "documents/paper", "revision": "confirmed"}
    assert transport == [("POST", "/workspaces/owned/documents")]


@pytest.mark.asyncio
async def test_disabled_sidecar_still_blocks_catalog_and_operations(transport, monkeypatch):
    monkeypatch.setattr(config.agents, "workspace_enabled", False)
    with pytest.raises(client.WorkspaceUnavailable):
        await client.document_profiles()
    assert (
        await client.create_document_project(
            {"workspace_id": "owned", "token": "opaque"},
            path="documents/paper",
            profile_id="generic_document",
            mode="draft",
            locale="ru-RU",
            expected_revision="base",
            fence=1,
        )
        is None
    )
    assert transport == []


@pytest.mark.asyncio
async def test_catalog_does_not_enable_implicit_allocation(transport):
    await client.document_profiles()
    assert await client.ensure_workspace(None, "thread", "owner") is None
    assert transport == [("GET", "/document-profiles")]


@pytest.mark.parametrize("configured,override", [(True, False), (False, True)])
@pytest.mark.asyncio
async def test_admin_autocreate_overlay_does_not_change_passive_catalog_access(
    transport, monkeypatch, configured, override
):
    from service.services.admin.application.runtime_settings import runtime_settings

    monkeypatch.setattr(config.agents, "workspace_autocreate", configured)
    monkeypatch.setattr(
        runtime_settings,
        "get_agents",
        lambda name, default=None: override if name == "workspace_autocreate" else default,
    )
    assert client._implicit_creation_config()[0] is override
    assert client._explicit_creation_config()[0] is True
    assert (await client.document_profiles())["profiles"]
    assert transport == [("GET", "/document-profiles")]
