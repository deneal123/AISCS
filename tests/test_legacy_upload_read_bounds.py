"""The compatibility upload route retains its contract without an unbounded read."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile

from service.models.auth_models import AuthProfile
from service.models.key_value import ServiceType, UserTypes
from service.services.files.presentation.routers.files_api import files_api
from service.settings import config


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_size", [None, 1, 100])
@pytest.mark.parametrize("size", [1, 7, 8, 100])
async def test_legacy_upload_bounds_read_and_preserves_allowed_bytes(
    declared_size, size, monkeypatch
):
    monkeypatch.setattr(config.file.settings, "max_file_size_byte", 8)
    monkeypatch.setattr(config.file.settings, "allowed_extensions", [".png"])
    content = bytes(range(size))
    upload = UploadFile(file=BytesIO(content), filename="fixture.PNG", size=declared_size)
    read = AsyncMock(wraps=upload.read)
    monkeypatch.setattr(upload, "read", read)
    owner = uuid4()
    profile = AuthProfile(user_id=owner, fingerprint=None, type=UserTypes.REGISTERED)
    saved = SimpleNamespace(file_id=str(uuid4()))
    save = AsyncMock(return_value=saved)
    if size > 8:
        with pytest.raises(HTTPException) as error:
            await files_api.upload_handler(
                profile=profile,
                mode=ServiceType.CHAT,
                file=upload,
                service=SimpleNamespace(save=save),
            )
        assert error.value.status_code == 400
        assert error.value.detail == "File too large. Max size: 8 bytes."
        save.assert_not_awaited()
    else:
        result = await files_api.upload_handler(
            profile=profile,
            mode=ServiceType.CHAT,
            file=upload,
            service=SimpleNamespace(save=save),
        )
        assert result is saved
        save.assert_awaited_once_with(
            user_id=owner, mode=ServiceType.CHAT, file_name="fixture.PNG", file_content=content
        )
    read.assert_awaited_once_with(9)
    assert upload.file.tell() == min(size, 9)
