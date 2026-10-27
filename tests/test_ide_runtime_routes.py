from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide import runtime as api
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def route_fixture():
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    owner, thread, repo = uuid4(), uuid4(), uuid4()
    service = SimpleNamespace(
        status=AsyncMock(return_value={"workspace": {"state": "not_created"}}),
        provision=AsyncMock(return_value={"workspace": {"state": "ready"}}),
    )
    app.dependency_overrides[api.get_ide_runtime] = lambda: service
    return app, service, RepositoryScope(thread, owner, repo)


def test_status_and_provision_require_auth_before_service(route_fixture):
    app, service, scope = route_fixture
    path = f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/runtime"
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.post(path, json={}).status_code == 401
    service.status.assert_not_awaited()
    service.provision.assert_not_awaited()


def test_read_and_explicit_provision_have_distinct_methods_and_owned_scope(route_fixture):
    app, service, scope = route_fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    path = f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/runtime"
    with TestClient(app) as client:
        assert client.get(path).json()["workspace"]["state"] == "not_created"
        service.provision.assert_not_awaited()
        assert client.post(path, json={}).json()["workspace"]["state"] == "ready"
        for key in ("user_id", "workspace_id", "allocation_id", "expires_at", "policy", "root"):
            assert client.post(path, json={key: "arbitrary"}).status_code == 422
    service.status.assert_awaited_once_with(scope)
    service.provision.assert_awaited_once_with(scope)


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (IdeRepositoryNotFound, 404, "ide_repository_not_found"),
        (RepositoryOperationalError, 503, "ide_repository_unavailable"),
    ],
)
def test_repository_failures_are_not_a_ready_or_empty_runtime(route_fixture, failure, status, code):
    app, service, scope = route_fixture
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    service.provision.side_effect = failure("PRIVATE_DATABASE_BODY")
    with TestClient(app) as client:
        response = client.post(
            f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/runtime", json={}
        )
    assert response.status_code == status
    assert response.json() == {"detail": code}
