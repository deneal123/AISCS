"""Failed upload processing never reflects internal data or reaches billing/indexing."""

import asyncio
import traceback
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient

from service.composition.state import (
    get_billing_service,
    get_chat_application_service,
    get_optional_redis_client,
)
from service.services.chat.application.use_cases.upload_file_use_case import (
    AttachmentIntentConflict,
    AttachmentPersistenceError,
)
from service.services.chat.infrastructure.media.whisper_local_transcriber import (
    TranscriptionTooExpensive,
)
from service.services.chat.presentation.http import upload_api
from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from service.shared.security.auth_checker import check_auth

MARKER = "PRIVATE_UPLOAD_PROXY_CREDENTIAL_PROVIDER_BODY"
CASES = [
    (ValueError, 400),
    (OverflowError, 413),
    (TranscriptionTooExpensive, 402),
    (AttachmentPersistenceError, 503),
    (AttachmentIntentConflict, 409),
    (RuntimeError, 500),
]


@pytest.fixture
def boundary(monkeypatch):
    profile = SimpleNamespace(user_id=uuid4())
    service = SimpleNamespace(file_service=SimpleNamespace(save=AsyncMock()))
    billing = SimpleNamespace(
        has_sufficient_credits=AsyncMock(return_value=True), charge=AsyncMock()
    )
    execute = AsyncMock()
    monkeypatch.setattr(
        upload_api, "get_upload_use_case", lambda _: SimpleNamespace(execute=execute)
    )
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    transcription = AsyncMock()
    image = AsyncMock()
    index = Mock()
    monkeypatch.setattr(upload_api, "_charge_transcription", transcription)
    monkeypatch.setattr(upload_api, "_charge_image_usage", image)
    monkeypatch.setattr(upload_api, "_schedule_graph_indexing", index)
    return SimpleNamespace(
        profile=profile,
        service=service,
        billing=billing,
        execute=execute,
        transcription=transcription,
        image=image,
        index=index,
    )


def assert_no_followup(boundary):
    boundary.execute.assert_awaited_once()
    boundary.billing.charge.assert_not_awaited()
    boundary.transcription.assert_not_awaited()
    boundary.image.assert_not_awaited()
    boundary.index.assert_not_called()
    boundary.service.file_service.save.assert_not_awaited()


async def invoke(boundary):
    file = UploadFile(file=BytesIO(b"synthetic"), filename="fixture.txt")
    try:
        return await upload_api.upload_file_to_chat(
            profile=boundary.profile,
            file=file,
            thread_id="",
            transcription_mode="local",
            transcription_model="",
            chat_application_service=boundary.service,
            billing_service=boundary.billing,
            redis_client=None,
            upload_intent_id=None,
        )
    finally:
        await file.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", CASES)
async def test_direct_upload_error_has_static_detail_and_no_raw_cause(kind, status, boundary):
    boundary.execute.side_effect = kind(MARKER)
    with pytest.raises(HTTPException) as caught:
        await invoke(boundary)
    assert caught.value.status_code == status
    assert MARKER not in str(caught.value.detail)
    assert MARKER not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__
    assert_no_followup(boundary)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,status", CASES)
async def test_http_upload_failure_returns_no_private_body_or_phantom_file(kind, status, boundary):
    boundary.execute.side_effect = kind(MARKER)
    app = FastAPI()
    app.include_router(upload_api.upload_router, prefix="/api/chats")
    setup_exception_handlers(app)
    app.dependency_overrides[check_auth] = lambda: boundary.profile
    app.dependency_overrides[get_billing_service] = lambda: boundary.billing
    app.dependency_overrides[get_chat_application_service] = lambda: boundary.service
    app.dependency_overrides[get_optional_redis_client] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.post(
            "/api/chats/upload", files={"file": ("fixture.txt", b"synthetic", "text/plain")}
        )
    assert response.status_code == status
    assert MARKER not in response.text
    assert set(response.json()) == {"error"}
    assert "file_id" not in response.json()
    if status == 402:
        assert "Пополните баланс" in response.json()["error"]["message"]
    assert_no_followup(boundary)


@pytest.mark.asyncio
async def test_upload_cancellation_never_becomes_processing_error_or_charge(boundary):
    boundary.execute.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await invoke(boundary)
    assert_no_followup(boundary)
