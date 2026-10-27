"""Application intake reads at most the configured limit plus one sentinel byte."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from service.models.auth_models import AuthProfile
from service.models.key_value import UserTypes
from service.services.chat.application.use_cases.upload_file_use_case import (
    AttachmentPersistenceError,
)
from service.services.chat.presentation.http import upload_api
from service.services.chat.presentation.routers.chat_api import work_intake
from service.settings import config


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["chat", "work"])
@pytest.mark.parametrize("declared_size", [None, 1, 100])
async def test_oversized_source_read_is_bounded_and_never_processed(
    surface, declared_size, monkeypatch
):
    monkeypatch.setattr(config.agents, "upload_max_bytes", 8)
    file = UploadFile(file=BytesIO(b"x" * 100), filename="fixture.md", size=declared_size)
    read = AsyncMock(wraps=file.read)
    monkeypatch.setattr(file, "read", read)
    save = AsyncMock()
    execute = AsyncMock(side_effect=OverflowError("File too large"))
    import_workspace = AsyncMock()
    monkeypatch.setattr(
        upload_api, "get_upload_use_case", lambda _: SimpleNamespace(execute=execute)
    )
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        if surface == "chat":
            await upload_api.upload_file_to_chat(
                profile=AuthProfile(user_id=uuid4(), fingerprint=None, type=UserTypes.REGISTERED),
                file=file,
                thread_id="",
                transcription_mode="local",
                transcription_model="",
                chat_application_service=SimpleNamespace(file_service=SimpleNamespace(save=save)),
                billing_service=SimpleNamespace(
                    has_sufficient_credits=AsyncMock(return_value=True)
                ),
                redis_client=None,
                upload_intent_id=None,
            )
        else:
            await work_intake.persist_and_import_uploaded_file(
                file=file,
                user_id=uuid4(),
                file_service=SimpleNamespace(save=save),
                import_workspace=import_workspace,
            )
    assert error.value.status_code == 413
    read.assert_awaited_once_with(9)
    assert file.file.tell() == 9
    execute.assert_not_awaited()
    save.assert_not_awaited()
    import_workspace.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["chat", "work"])
@pytest.mark.parametrize("size", [1, 7, 8])
async def test_source_within_limit_reaches_processing_without_truncation(
    surface, size, monkeypatch
):
    monkeypatch.setattr(config.agents, "upload_max_bytes", 8)
    content = bytes(range(size))
    file = UploadFile(file=BytesIO(content), filename="fixture.md", size=100)
    read = AsyncMock(wraps=file.read)
    monkeypatch.setattr(file, "read", read)
    execute = AsyncMock(side_effect=AttachmentPersistenceError("fixture unavailable"))
    save = AsyncMock(side_effect=OSError("fixture unavailable"))
    monkeypatch.setattr(
        upload_api, "get_upload_use_case", lambda _: SimpleNamespace(execute=execute)
    )
    monkeypatch.setattr(upload_api, "_affordable_transcription_sec", AsyncMock(return_value=None))
    with pytest.raises(HTTPException) as error:
        if surface == "chat":
            await upload_api.upload_file_to_chat(
                profile=AuthProfile(user_id=uuid4(), fingerprint=None, type=UserTypes.REGISTERED),
                file=file,
                thread_id="",
                transcription_mode="local",
                transcription_model="",
                chat_application_service=SimpleNamespace(file_service=SimpleNamespace(save=save)),
                billing_service=SimpleNamespace(
                    has_sufficient_credits=AsyncMock(return_value=True)
                ),
                redis_client=None,
                upload_intent_id=None,
            )
        else:
            await work_intake.persist_and_import_uploaded_file(
                file=file,
                user_id=uuid4(),
                file_service=SimpleNamespace(save=save),
                import_workspace=AsyncMock(),
            )
    assert error.value.status_code == 503
    read.assert_awaited_once_with(9)
    observed = (
        execute.await_args.kwargs["content_bytes"]
        if surface == "chat"
        else (save.await_args.kwargs["file_content"])
    )
    assert observed == content
    assert file.file.tell() == size
