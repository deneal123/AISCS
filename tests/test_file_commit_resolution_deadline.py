"""Uncertain metadata acknowledgement must not hold upload settlement indefinitely."""

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.files.application import file_saver_service
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_uncertain_commit_lookup_has_deadline_and_retains_object(monkeypatch, streaming):
    closed = asyncio.Event()
    timeout = asyncio.timeout
    warning = Mock()

    def deadline(seconds):
        assert seconds == 30
        return timeout(0.01)

    async def unresolved(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(asyncio, "timeout", deadline)
    monkeypatch.setattr(file_saver_service.logger, "warning", warning)
    repository = SimpleNamespace(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(side_effect=RuntimeError("PRIVATE-ACK-BODY")),
        fetch_user_file_by_name=AsyncMock(side_effect=unresolved),
    )
    storage = SimpleNamespace(
        build_file_path=lambda *_args: "fixture/unique-attempt",
        upload_file=AsyncMock(return_value="internal://fixture"),
        upload_file_stream=AsyncMock(return_value="internal://fixture"),
        delete_file=AsyncMock(),
    )
    owner, intent = uuid4(), uuid4()
    saver = FileSaverService(repository, "fixture", storage)
    payload = b"synthetic artifact"

    async def chunks():
        yield payload

    call = (
        saver.save_stream(
            owner,
            ServiceType.CHAT,
            "final.pdf",
            chunks(),
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_intent_id=intent,
        )
        if streaming
        else saver.save(owner, ServiceType.CHAT, "final.pdf", payload, upload_intent_id=intent)
    )
    with pytest.raises(RuntimeError, match="^metadata_unconfirmed$"):
        await asyncio.wait_for(call, 0.2)
    assert closed.is_set()
    repository.add_file_metadata.assert_awaited_once()
    repository.fetch_user_file_by_name.assert_awaited_once_with(owner, "fixture/unique-attempt")
    storage.delete_file.assert_not_awaited()
    warning.assert_called_once_with(
        "file metadata commit unresolved",
        extra={"component": "file_library", "failure_code": "unavailable"},
    )
