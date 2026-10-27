"""A failed download capability is unavailable, never an internal-key redirect."""

import asyncio
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "s3://PRIVATE_BUCKET/PRIVATE_KEY",
        "uploads/CHAT/PRIVATE_KEY.pdf",
        "//storage.example/PRIVATE_KEY",
        "https://user:password@storage.example/PRIVATE_KEY",
        "https:///PRIVATE_KEY",
        "https://storage.example:invalid/PRIVATE_KEY",
        "https://storage.example:65536/PRIVATE_KEY",
        "https://storage.example:0/PRIVATE_KEY",
        "https://storage.example/file\r\nPRIVATE_KEY",
        "exception",
    ],
)
async def test_invalid_capability_is_bounded_unavailable_without_storage_leak(value, caplog):
    owner, file_id = uuid4(), uuid4()
    signer = AsyncMock(return_value=value)
    if value == "exception":
        signer.side_effect = ValueError("PRIVATE_PROVIDER_BODY")
    service = FileSaverService.__new__(FileSaverService)
    service.storage = SimpleNamespace(get_presigned_url=signer)
    service.repository = SimpleNamespace(
        fetch_user_file_by_id=AsyncMock(
            return_value=SimpleNamespace(
                id=file_id, file_url="s3://fixture/owned", file_name="PRIVATE_KEY"
            )
        )
    )
    app = FastAPI()
    app.include_router(files_router)
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=owner, fingerprint=None, type=UserTypes.REGISTERED
    )
    app.dependency_overrides[get_file_saver_service] = lambda: service
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        download = await client.get(f"/api/service/files/v1/{file_id}/download")
        assert download.status_code == 503
        assert "location" not in download.headers
        assert download.json() == {"detail": "File is temporarily unavailable"}
        metadata = await client.get(f"/api/service/files/v1/{file_id}")
        assert metadata.status_code == 200
        assert metadata.json()["download_url"] is None
    assert "PRIVATE_KEY" not in download.text + caplog.text
    assert "PRIVATE_PROVIDER_BODY" not in download.text + metadata.text + caplog.text
    assert signer.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_valid_signed_download_is_returned_without_rewriting(scheme):
    capability = f"{scheme}://storage.example/object?X-Amz-Signature=opaque"
    service = FileSaverService.__new__(FileSaverService)
    service.storage = SimpleNamespace(get_presigned_url=AsyncMock(return_value=capability))
    assert await service.get_presigned_url_by_key(file_key="owned") == capability


@pytest.mark.asyncio
async def test_signing_cancellation_propagates_without_retry():
    signer = AsyncMock(side_effect=asyncio.CancelledError())
    service = FileSaverService.__new__(FileSaverService)
    service.storage = SimpleNamespace(get_presigned_url=signer)
    with pytest.raises(asyncio.CancelledError):
        await service.get_presigned_url_by_key(file_key="owned")
    signer.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_download_retry_reuses_owned_file_after_transient_signing_failure():
    owner, file_id = uuid4(), uuid4()
    capability = "https://storage.example/owned?X-Amz-Signature=opaque"
    signer = AsyncMock(side_effect=[RuntimeError("PRIVATE_PROVIDER_BODY"), capability])
    service = FileSaverService.__new__(FileSaverService)
    service.storage = SimpleNamespace(get_presigned_url=signer)
    repository = SimpleNamespace(
        fetch_user_file_by_id=AsyncMock(
            return_value=SimpleNamespace(id=file_id, file_url="s3://owned", file_name="owned")
        ),
        add_file_metadata=AsyncMock(),
        delete_file_metadata=AsyncMock(),
    )
    service.repository = repository
    app = FastAPI()
    app.include_router(files_router)
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=owner, fingerprint=None, type=UserTypes.REGISTERED
    )
    app.dependency_overrides[get_file_saver_service] = lambda: service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        route = f"/api/service/files/v1/{file_id}/download"
        first = await client.get(route)
        assert first.status_code == 503 and "location" not in first.headers
        second = await client.get(route)
        assert second.status_code == 307 and second.headers["location"] == capability
    assert signer.await_count == 2  # Two explicit HTTP requests, no hidden retry.
    assert all(
        call.args == (owner, file_id) for call in repository.fetch_user_file_by_id.await_args_list
    )
    repository.add_file_metadata.assert_not_awaited()
    repository.delete_file_metadata.assert_not_awaited()
