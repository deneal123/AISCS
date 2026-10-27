from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.domain.ide.console import ConsoleError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide import console as api
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def route():
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    payload = {"execution_id": str(uuid4()), "generation": "a" * 64, "command": "python main.py"}
    receipt = {
        "execution_id": payload["execution_id"],
        "generation": payload["generation"],
        "repository_id": str(scope.repository_id),
        "state": "unknown",
        "result": None,
    }
    service = SimpleNamespace(
        execute=AsyncMock(return_value=receipt), status=AsyncMock(return_value=receipt)
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_console] = lambda: service
    path = f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/console"
    return SimpleNamespace(**locals())


def test_console_requires_auth_before_dispatch(route):
    s = route
    with TestClient(s.app) as client:
        assert client.post(s.path, json=s.payload).status_code == 401
    s.service.execute.assert_not_awaited()


def test_console_derives_owner_and_keeps_success_private(route):
    s = route
    s.app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=s.scope.user_id)
    with TestClient(s.app) as client:
        response = client.post(s.path, json=s.payload, headers={"X-Workspace-Session": "session"})
        read = client.get(f"{s.path}/{s.payload['execution_id']}")
    assert response.status_code == read.status_code == 200
    assert response.headers["cache-control"] == read.headers["cache-control"] == "private, no-store"
    assert s.payload["command"] not in response.text
    assert s.service.execute.await_args.args[0] == s.scope
    assert s.service.execute.await_args.args[2] == "session"


def test_invalid_body_and_unknown_receipt_are_closed_private_errors(route):
    s = route
    s.app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=s.scope.user_id)
    s.service.status.side_effect = ConsoleError("ide_console_status_unknown")
    with TestClient(s.app) as client:
        response = client.post(s.path, json={**s.payload, "command": "SECRET\nCOMMAND"})
        read = client.get(f"{s.path}/{s.payload['execution_id']}")
    assert response.status_code == 422 and "SECRET" not in response.text
    assert read.status_code == 503
    assert response.headers["cache-control"] == read.headers["cache-control"] == "private, no-store"
    s.service.execute.assert_not_awaited()


def test_agent_history_checks_owner_and_is_read_only_private(route, monkeypatch):
    s = route
    s.app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=s.scope.user_id)
    s.service.runtime = SimpleNamespace(_check_owner=AsyncMock())
    connector = object()
    monkeypatch.setattr(
        api,
        "get_app_container",
        lambda _: SimpleNamespace(infra=SimpleNamespace(pg_connector=connector)),
    )
    read = AsyncMock(return_value={"entries": []})
    monkeypatch.setattr(api, "history", read)
    with TestClient(s.app) as client:
        response = client.get(
            s.path.removesuffix("console") + "agent-commands", params={"generation": "a" * 64}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    s.service.runtime._check_owner.assert_awaited_once_with(s.scope)
    read.assert_awaited_once_with(connector, s.scope, "a" * 64)
    s.service.execute.assert_not_awaited()
