"""HTTP download checks the owner before signing and bounds repository failures."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from service.composition.state import get_file_saver_service
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.presentation.routers.files_api.files_api import files_router
from service.shared.security.auth_checker import check_auth


def fixture_app(*, authenticated=True, failure=None):
    owner = uuid4()
    service = FileSaverService.__new__(FileSaverService)
    service.repository = SimpleNamespace(
        fetch_user_file_by_id=AsyncMock(return_value=None, side_effect=failure)
    )
    service.storage = SimpleNamespace(get_presigned_url=AsyncMock())
    app = FastAPI()
    app.include_router(files_router)
    app.dependency_overrides[get_file_saver_service] = lambda: service
    if authenticated:
        app.dependency_overrides[check_auth] = lambda: AuthProfile(
            user_id=owner, fingerprint=None, type=UserTypes.REGISTERED
        )
    return app, service, owner


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/download"])
async def test_missing_owned_row_never_reaches_storage_signer(suffix):
    app, service, owner = fixture_app()
    file_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/service/files/v1/{file_id}{suffix}")
    assert response.status_code == 404
    assert response.json() == {"detail": "File not found"}
    assert "location" not in response.headers
    service.repository.fetch_user_file_by_id.assert_awaited_once_with(owner, file_id)
    service.storage.get_presigned_url.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/download"])
async def test_anonymous_request_cannot_resolve_or_sign_file(suffix):
    app, service, _ = fixture_app(authenticated=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/service/files/v1/{uuid4()}{suffix}")
    assert response.status_code == 401
    assert "location" not in response.headers
    service.repository.fetch_user_file_by_id.assert_not_awaited()
    service.storage.get_presigned_url.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["", "/download"])
async def test_repository_outage_is_retriable_without_raw_body_or_redirect(suffix):
    app, service, _ = fixture_app(failure=RuntimeError("PRIVATE_DB_DSN_BODY"))
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(f"/api/service/files/v1/{uuid4()}{suffix}")
    assert response.status_code == 503
    assert response.json() == {"detail": "File is temporarily unavailable"}
    assert "location" not in response.headers
    assert "PRIVATE" not in response.text
    service.storage.get_presigned_url.assert_not_awaited()
