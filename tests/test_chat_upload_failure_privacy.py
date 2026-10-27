"""Storage bodies never escape the attachment persistence boundary."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from service.composition.state import (
    get_billing_service,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.application.use_cases import upload_file_use_case
from service.services.chat.application.use_cases.upload_file_use_case import UploadFileUseCase
from service.services.chat.presentation.http import upload_api
from service.shared.security.auth_checker import check_auth


@pytest.mark.asyncio
@pytest.mark.parametrize("precheck_failure", [False, True])
async def test_storage_failure_is_bounded_in_http_response_and_logs(
    precheck_failure, monkeypatch, caplog
):
    marker = "PRIVATE_ATTACHMENT_STORAGE_BODY"
    saver = SimpleNamespace(save=AsyncMock(side_effect=OSError(marker)))
    use_case = UploadFileUseCase(media_analysis_port=object(), file_service=saver)
    monkeypatch.setattr(upload_api, "get_upload_use_case", lambda _: use_case)
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    app = FastAPI()
    app.include_router(upload_api.upload_router, prefix="/api/chats")
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=uuid4(), fingerprint=None, type=UserTypes.REGISTERED
    )
    app.dependency_overrides[get_chat_application_service] = lambda: SimpleNamespace(
        file_service=saver
    )
    app.dependency_overrides[get_billing_service] = lambda: SimpleNamespace(
        has_sufficient_credits=AsyncMock(
            return_value=True, side_effect=OSError(marker) if precheck_failure else None
        )
    )
    app.dependency_overrides[get_optional_redis_client] = lambda: None
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(upload_file_use_case.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(upload_file_use_case.logger, "propagate", False)
    monkeypatch.setattr(upload_api.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(upload_api.logger, "propagate", False)
    caplog.set_level(logging.DEBUG, logger=upload_api.logger.name)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post(
            "/api/chats/upload", files={"file": ("fixture.md", b"fixture", "text/markdown")}
        )
    assert response.status_code == 503
    assert "file_id" not in response.json()
    assert marker not in response.text + caplog.text
    records = [record for record in caplog.records if "attachment" in record.getMessage()]
    assert records
    assert all(record.exc_info is None for record in records)
    assert all(getattr(record, "failure_code", None) == "unavailable" for record in records)
