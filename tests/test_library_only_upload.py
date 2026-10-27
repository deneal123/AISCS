import io
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from service.services.chat.presentation.routers.chat_api import library_upload_routes as api
from service.services.chat.presentation.routers.chat_api.work_intake import (
    persist_and_import_uploaded_file,
)
from service.shared.security.auth_checker import check_auth


@pytest.mark.asyncio
async def test_library_only_persists_without_even_resolving_an_import_source():
    file_id, intent, owner = uuid4(), uuid4(), uuid4()
    files = SimpleNamespace(
        save=AsyncMock(return_value=SimpleNamespace(file_id=file_id)),
        resolve_chat_library_import=AsyncMock(),
    )
    response = await persist_and_import_uploaded_file(
        file=UploadFile(filename="data.zip", file=io.BytesIO(b"PK\0\xff")),
        user_id=owner,
        file_service=files,
        import_workspace=None,
        upload_intent_id=intent,
    )
    assert (
        response["outcome"] == "library_uploaded"
        and response["workspace_status"] == "not_requested"
    )
    assert response["file"]["file_id"] == str(file_id)
    assert files.save.await_args.kwargs["upload_intent_id"] == intent
    files.resolve_chat_library_import.assert_not_awaited()


def test_library_only_route_checks_thread_owner_and_needs_no_runtime_or_lease():
    owner, file_id = uuid4(), uuid4()
    service = SimpleNamespace(ensure_thread_owner=AsyncMock())
    files = SimpleNamespace(
        save=AsyncMock(return_value=SimpleNamespace(file_id=file_id)),
        resolve_chat_library_import=AsyncMock(),
    )
    app = FastAPI()
    app.include_router(api.router, prefix="/api/chats")
    app.dependency_overrides[api.get_chat_application_service] = lambda: service
    app.dependency_overrides[api.get_file_saver_service] = lambda: files
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/chats/t/work/library/upload", files={"file": ("a.txt", b"body")}
            ).status_code
            == 401
        )
        service.ensure_thread_owner.assert_not_awaited()
        app.dependency_overrides[check_auth] = lambda: SimpleNamespace(user_id=owner)
        response = client.post(
            "/api/chats/t/work/library/upload", files={"file": ("a.txt", b"body")}
        )
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    service.ensure_thread_owner.assert_awaited_once_with("t", str(owner))
    files.resolve_chat_library_import.assert_not_awaited()
