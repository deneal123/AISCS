from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from service.services.chat.application.ide.edits import IdeEditService
from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import generation_tag
from service.services.chat.presentation.routers.chat_api.ide import edits as api
from service.shared.presentation.handlers.exceptions_handlers import validation_exception_handler
from service.shared.security.auth_checker import check_auth
from tests.test_ide_edits import setup_runtime
from tests.test_workspace_collaboration import FakeRedis


def test_mutation_routes_require_auth_and_reject_binding_injection(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_ide_runtime] = lambda: runtime
    app.dependency_overrides[api.get_optional_redis_client] = lambda: FakeRedis()
    prefix = f"/api/chats/{scope.thread_id}/ide/repositories/{scope.repository_id}"
    bodies = {
        "files/write": dict(
            path="main.py", generation=generation_tag(attempt), operation="file", fence=1
        ),
        "files/lease": dict(path="main.py", generation=generation_tag(attempt), action="acquire"),
        "git": dict(generation=generation_tag(attempt), operation="init"),
        "files/move": dict(
            path="main.py",
            destination="src/main.py",
            generation=generation_tag(attempt),
            fence=1,
            destination_fence=2,
        ),
    }
    with TestClient(app) as client:
        for endpoint, body in bodies.items():
            assert client.post(prefix + "/" + endpoint, json=body).status_code == 401
        runtime.resolve.assert_not_awaited()
        app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=scope.user_id)
        assert (
            client.post(
                prefix + "/git", json={**bodies["git"], "replace_pristine_starter": True}
            ).status_code
            == 422
        )
        assert (
            client.post(
                prefix + "/git", json={**bodies["git"], "clone_intent_id": str(scope.repository_id)}
            ).status_code
            == 422
        )
        for endpoint, body in bodies.items():
            response = client.post(
                prefix + "/" + endpoint, json={**body, "workspace_id": "PRIVATE"}
            )
            assert response.status_code == 422
            assert "PRIVATE" not in response.text
    runtime.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_browser_lease_and_old_fence_cannot_write(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "test-only-coordination-secret")
    scope, attempt, runtime = setup_runtime()
    service = IdeEditService(runtime, FakeRedis())
    params = dict(
        path="main.py", generation=generation_tag(attempt), session="browser-session-0001"
    )
    lease = await service.lease(scope, **params, action="acquire", fence=None)
    for changes in (
        {"session": "browser-session-0002", "fence": lease["fence"]},
        {"fence": lease["fence"] + 1},
    ):
        with pytest.raises(IdeEditError, match="ide_edit_lease_changed"):
            await service.write(
                scope,
                **{**params, **changes},
                operation="file",
                content="text",
                expected_digest=None,
            )
    runtime.client.write.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_repository_never_reaches_file_or_git_transport():
    scope, attempt, runtime = setup_runtime()
    runtime.resolve.side_effect = IdeRepositoryNotFound()
    runtime.client.git = AsyncMock()
    service = IdeEditService(runtime, FakeRedis())
    params = dict(generation=generation_tag(attempt), session="browser-session-0001")
    with pytest.raises(IdeRepositoryNotFound):
        await service.write(
            scope,
            **params,
            path="main.py",
            fence=1,
            operation="file",
            content="",
            expected_digest=None,
        )
    with pytest.raises(IdeRepositoryNotFound):
        await service.git(scope, **params, operation="init")
    runtime.client.git.assert_not_awaited()
    runtime.client.write.assert_not_awaited()
