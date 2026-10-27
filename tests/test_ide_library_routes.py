from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.services.chat.domain.ide.runtime import RepositoryScope
from service.services.chat.presentation.routers.chat_api.ide import library as api
from service.shared.security.auth_checker import check_auth


def test_library_copy_route_is_owned_private_and_identifier_only(monkeypatch):
    thread, owner, repo, file_id = [uuid4() for _ in range(4)]
    copier = AsyncMock(return_value={"written": True})
    monkeypatch.setattr(api, "copy_library_file", copier)
    runtime, files = object(), object()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_ide_runtime] = lambda: runtime
    app.dependency_overrides[api.get_file_saver_service] = lambda: files
    app.dependency_overrides[api.get_optional_redis_client] = lambda: None
    body = dict(path="assets/data.bin", generation="a" * 64, fence=3)
    url = f"/api/chats/{thread}/ide/repositories/{repo}/library/{file_id}/copy"
    with TestClient(app) as client:
        assert client.post(url, json=body).status_code == 401
        copier.assert_not_awaited()
        app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=owner)
        for extra in ["url", "content", "token", "workspace_id", "user_id", "overwrite"]:
            assert client.post(url, json={**body, extra: "forbidden"}).status_code == 422
        copier.assert_not_awaited()
        response = client.post(
            url, json=body, headers={"X-Workspace-Session": "browser-session-0123"}
        )
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    args = copier.await_args
    assert args.args[1:] == (files, RepositoryScope(thread, owner, repo))
    assert args.kwargs == {**body, "file_id": file_id, "session": "browser-session-0123"}
