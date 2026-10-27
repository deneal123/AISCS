"""Cancelled local uploads finish their exact writer before compensation."""

import asyncio
import hashlib
import io
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("writer_failed", [False, True])
async def test_repeated_disconnect_cannot_race_local_writer_and_cleanup(
    tmp_path, monkeypatch, streaming, writer_failed, caplog
):
    entered, release = threading.Event(), threading.Event()
    original_open = Path.open

    def held_open(path, mode="r", *args, **kwargs):
        if mode == "wb" and path.is_relative_to(tmp_path):
            entered.set()
            assert release.wait(3)
            if writer_failed:
                raise OSError("private-local-write-marker")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", held_open)
    storage = LocalFileStorage(tmp_path)
    repository = SimpleNamespace(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(),
    )
    saver = FileSaverService(repository, "fixture", storage)
    owner, intent = uuid4(), uuid4()
    payload = b"synthetic local upload"

    async def chunks():
        yield payload

    operation = (
        saver.save_stream(
            owner,
            ServiceType.CHAT,
            "notes.md",
            chunks(),
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_intent_id=intent,
        )
        if streaming
        else saver.save(owner, ServiceType.CHAT, "notes.md", payload)
    )
    task = asyncio.create_task(operation)
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "cancellation returned while the local writer was still active"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    repository.add_file_metadata.assert_not_awaited()
    assert not list(tmp_path.rglob("*.md"))
    assert "private-local-write-marker" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_normal_local_upload_keeps_content_and_caller_stream_open(tmp_path, streaming):
    storage = LocalFileStorage(tmp_path)
    content = b"local-storage-contract"
    stream = io.BytesIO(content)
    if streaming:
        result = await storage.upload_file_stream(
            file_key="fixture.md", stream=stream, length=len(content)
        )
    else:
        result = await storage.upload_file(file_key="fixture.md", file_data=content)
    assert Path(result).read_bytes() == content
    assert not stream.closed
