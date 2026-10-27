from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.provider_status import project_provider_status


def test_public_status_is_bounded_and_excludes_private_health_fields():
    payload = {
        "providers": [
            {
                "id": "gigachat",
                "label": "GigaChat",
                "primary": True,
                "state": "ready",
                "checked_at": 123.0,
                "error": "PRIVATE_UPSTREAM",
                "api_key": "PRIVATE_KEY",
            },
            {"id": "routerai", "label": "RouterAI", "state": "ready"},
            {"id": "http://private.invalid", "label": "PRIVATE_URL", "state": "ready"},
        ]
    }
    result = project_provider_status(payload, {"routerai"})
    assert result["state"] == "available"
    assert (result["ready"], result["total"]) == (1, 1)
    assert len(result["providers"]) == 2
    assert result["providers"][1]["state"] == "disabled"
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize("data", [None, {}, {"providers": "invalid"}])
def test_missing_evidence_is_unknown_not_a_false_outage(data):
    assert project_provider_status(data, set()) == {
        "state": "unknown",
        "ready": 0,
        "total": 0,
        "providers": [],
    }


def test_authoritative_block_overrides_an_older_positive_observation():
    result = project_provider_status(
        {
            "providers": [
                {"id": "gigachat", "label": "GigaChat", "state": "ready"},
            ]
        },
        set(),
        {"gigachat"},
    )
    assert result["state"] == "unavailable"
    assert result["ready"] == 0


@pytest.mark.parametrize(
    "disabled,blocked,state",
    [(set(), set(), "ready"), ({"local"}, set(), "disabled"), (set(), {"local"}, "unavailable")],
)
def test_local_provider_uses_shared_policy_and_safe_russian_label(disabled, blocked, state):
    result = project_provider_status(
        {
            "providers": [
                {"id": "local", "label": "PRIVATE_URL", "state": "ready", "api_key": "PRIVATE_KEY"}
            ]
        },
        disabled,
        blocked,
    )
    assert result["providers"][0]["label"] == "Локальная модель"
    assert result["providers"][0]["state"] == state
    assert "PRIVATE" not in str(result)


@pytest.mark.asyncio
async def test_user_route_requires_auth_and_reads_cached_status_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from service.infrastructure.agents_client import sidecar_providers
    from service.services.chat.presentation.routers.chat_api.chat_api import chat_router
    from service.shared.security.auth_checker import check_auth

    read = AsyncMock(return_value={"providers": []})
    monkeypatch.setattr(sidecar_providers, "fetch_provider_status", read)
    app = FastAPI()
    app.include_router(chat_router)
    # The endpoint's auth dependency is mandatory even though no admin data is exposed.
    route = next(
        route for route in app.routes if getattr(route, "path", "") == "/api/chats/providers/status"
    )
    assert any(dependency.call is check_auth for dependency in route.dependant.dependencies)
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(id=1)
    with TestClient(app) as client:
        response = client.get("/api/chats/providers/status")
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    read.assert_awaited_once()
