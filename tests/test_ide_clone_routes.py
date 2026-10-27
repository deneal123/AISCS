from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from service.services.chat.application.ide.repositories import IdeRepositoryNotFound
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide import edits as api
from service.shared.presentation.handlers.exceptions_handlers import (
    http_exception_handler,
    validation_exception_handler,
)
from service.shared.security.auth_checker import check_auth


def test_clone_routes_are_private_owned_and_accept_no_runtime_or_replacement_policy():
    thread, owner, source, intent = [uuid4() for _ in range(4)]
    service = SimpleNamespace(
        recover=AsyncMock(return_value={"attempt": None}),
        clone=AsyncMock(return_value={"state": "complete"}),
        status=AsyncMock(return_value={"state": "running"}),
    )
    app = FastAPI()
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_ide_clones] = lambda: service
    root = f"/api/chats/{thread}/ide/clones"
    body = dict(
        intent_id=str(intent),
        source_repository_id=str(source),
        origin="https://github.com/owner/repo",
    )
    with TestClient(app) as client:
        assert client.post(root, json=body).status_code == 401
        assert client.get(root + "/" + str(intent)).status_code == 401
        service.clone.assert_not_awaited()
        service.status.assert_not_awaited()
        recovery_path = f"/api/chats/{thread}/ide/repositories/{source}/clone-attempt"
        assert client.get(recovery_path).status_code == 401
        service.recover.assert_not_awaited()
        app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=owner)
        recovered = client.get(recovery_path)
        assert recovered.status_code == 200 and recovered.json() == {"attempt": None}
        assert "no-store" in recovered.headers["cache-control"]
        service.recover.assert_awaited_once_with(RepositoryScope(thread, owner, source))
        for key in ("workspace_id", "token", "replace_pristine_starter", "user_id", "retry"):
            response = client.post(root, json={**body, key: "PRIVATE_VALUE"})
            assert response.status_code == 422
            assert "PRIVATE_VALUE" not in response.text
        response = client.post(
            root, json=body, headers={"X-Workspace-Session": "browser-session-0001"}
        )
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        service.clone.assert_awaited_once_with(
            RepositoryScope(thread, owner, source),
            intent_id=intent,
            origin=body["origin"],
            branch="",
            session="browser-session-0001",
        )
        assert client.get(root + "/" + str(intent)).json() == {"state": "running"}
        service.status.assert_awaited_once_with(thread_id=thread, user_id=owner, intent_id=intent)
        service.status.side_effect = IdeRepositoryNotFound()
        assert client.get(root + "/" + str(intent)).status_code == 404
        service.clone.side_effect = IdeEditError("ide_git_not_empty")
        failed = client.post(root, json=body)
        assert failed.status_code == 409
        assert failed.json()["error"]["code"] == "ide_git_not_empty"
        assert "no-store" in failed.headers["cache-control"]
