"""Legacy storage-key downloads must obey the same ownership as opaque ID routes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from service.composition.state import get_chat_application_service
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.application.chat_application_service import ChatApplicationService
from service.services.chat.presentation.routers.chat_api.chat_api import chat_router
from service.services.files.application.file_saver_service import FileSaverService
from service.shared.security.auth_checker import check_auth


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["foreign", "missing", "database", "redirect", "bytes", "storage"])
async def test_legacy_download_is_owner_checked_and_fail_closed(case, caplog):
    owner = uuid4()
    marker = "PRIVATE_EXCEPTION_BODY_MUST_NOT_APPEAR"
    key = "uploads/CHAT/legacy.pdf"
    repository = SimpleNamespace(fetch_user_file_by_name=AsyncMock())
    if case in {"foreign", "missing"}:
        repository.fetch_user_file_by_name.return_value = None
    elif case == "database":
        repository.fetch_user_file_by_name.side_effect = RuntimeError(marker)
    else:
        repository.fetch_user_file_by_name.return_value = SimpleNamespace(file_name=key)
    files = FileSaverService.__new__(FileSaverService)
    files.repository = repository
    files.get_presigned_url_by_key = AsyncMock(
        return_value="https://storage.example/owned" if case == "redirect" else None
    )
    files.get_file_by_key = AsyncMock(return_value=b"%PDF-owned")
    if case == "storage":
        files.get_file_by_key.side_effect = RuntimeError(marker)
    service = ChatApplicationService.__new__(ChatApplicationService)
    service.file_service = files
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_chat_application_service] = lambda: service
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=owner, fingerprint="test", type=UserTypes.REGISTERED
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/chats/files/download",
            # A caller-supplied user ID cannot change the authenticated identity.
            params={"file_key": f"s3://private-bucket/{key}", "user_id": str(uuid4())},
        )
    repository.fetch_user_file_by_name.assert_awaited_once_with(owner, key)
    if case in {"foreign", "missing", "database"}:
        assert response.status_code == (503 if case == "database" else 404)
        files.get_presigned_url_by_key.assert_not_awaited()
        files.get_file_by_key.assert_not_awaited()
    elif case == "redirect":
        assert response.status_code == 307
        files.get_file_by_key.assert_not_awaited()
    elif case == "bytes":
        assert response.status_code == 200 and response.content == b"%PDF-owned"
    else:
        assert response.status_code == 503
    assert marker not in response.text and marker not in caplog.text
