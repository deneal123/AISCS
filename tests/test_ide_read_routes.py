import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.files import IdeReadError
from service.services.chat.domain.ide.runtime import (
    RepositoryScope,
    ResolvedRuntime,
    RuntimeAttempt,
    WorkspaceBinding,
    generation_tag,
)
from service.services.chat.presentation.routers.chat_api.ide import reads as api
from service.shared.security.auth_checker import check_auth


@pytest.fixture
def read_route():
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    attempt = RuntimeAttempt(uuid4(), int(time.time()) + 600, "ready", 1)
    binding = WorkspaceBinding("a" * 32, "PRIVATE_TOKEN", attempt.expires_at)
    service = SimpleNamespace(
        resolve=AsyncMock(return_value=ResolvedRuntime(attempt, binding)),
        runtime=SimpleNamespace(get_owned=AsyncMock(return_value=attempt)),
        client=SimpleNamespace(read=AsyncMock(return_value={"entries": [], "truncated": False})),
    )
    app.dependency_overrides[api.get_ide_runtime] = lambda: service
    return app, service, scope, generation_tag(attempt)


def path(scope, operation="tree"):
    return f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}/files/{operation}"


def test_tree_and_file_require_auth_before_private_resolution(read_route):
    app, service, scope, generation = read_route
    with TestClient(app) as client:
        assert client.post(path(scope), json={}).status_code == 401
        assert (
            client.post(
                path(scope, "read"), json={"path": "main.py", "generation": generation}
            ).status_code
            == 401
        )
    service.resolve.assert_not_awaited()
    service.client.read.assert_not_awaited()


def test_tree_binds_authenticated_owner_and_has_opaque_generation(read_route):
    app, service, scope, generation = read_route
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    with TestClient(app) as client:
        response = client.post(path(scope), json={})
    assert response.status_code == 200 and response.json()["generation"] == generation
    assert response.headers["cache-control"] == "private, no-store"
    assert "PRIVATE" not in response.text
    service.resolve.assert_awaited_once_with(scope)


def test_file_requires_selection_generation_and_rejects_target_injection(read_route):
    app, service, scope, generation = read_route
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    with TestClient(app) as client:
        assert client.post(path(scope, "read"), json={"path": "main.py"}).status_code == 422
        for key in ("workspace_id", "user_id", "allocation_id", "root", "token"):
            assert client.post(path(scope), json={key: "PRIVATE"}).status_code == 422
        assert (
            client.post(
                path(scope, "read"), json={"path": "main.py", "generation": generation}
            ).status_code
            == 200
        )
    service.resolve.assert_awaited_once_with(scope)
    assert service.client.read.await_args.kwargs == {"operation": "file", "path": "main.py"}


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (IdeRepositoryNotFound(), 404, "ide_repository_not_found"),
        (IdeReadError("ide_runtime_not_ready"), 409, "ide_runtime_not_ready"),
        (IdeReadError("ide_runtime_expired"), 410, "ide_runtime_expired"),
        (IdeReadError("PRIVATE_DETAILS"), 503, "ide_read_unavailable"),
    ],
)
def test_runtime_failures_do_not_become_empty_trees(read_route, failure, status, code):
    app, service, scope, _ = read_route
    app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
    service.resolve.side_effect = failure
    with TestClient(app) as client:
        response = client.post(path(scope), json={})
    assert response.status_code == status and response.json() == {"detail": code}
    assert response.headers["cache-control"] == "private, no-store"
    service.client.read.assert_not_awaited()
