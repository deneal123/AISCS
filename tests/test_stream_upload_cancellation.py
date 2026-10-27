"""Cancellation must not close a spool still owned by the blocking SDK."""

import asyncio
import hashlib
import threading
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_failure", [False, True])
@pytest.mark.parametrize("upload_mode", ["stream", "bytes"])
async def test_cancelled_stream_drains_sdk_then_compensates_without_metadata(
    remote_failure, upload_mode, caplog
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
    observed = []
    payload = b"%PDF-synthetic"

    def put_object(**kwargs):
        observed.append(kwargs["data"])
        started.set()
        try:
            if not release.wait(5):
                raise TimeoutError("test worker release missing")
            assert kwargs["data"].read() == payload
            if remote_failure:
                raise OSError("private transport marker")
        finally:
            finished.set()

    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._retry_attempts = 3
    storage._retry_backoff = 0
    storage._client = Mock(put_object=Mock(side_effect=put_object))

    async def delete_file(**kwargs):
        assert finished.is_set()
        cleanup_started.set()
        await cleanup_release.wait()

    storage.delete_file = AsyncMock(side_effect=delete_file)
    repository = Mock(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(),
    )
    saver = FileSaverService(repository, "generated", storage)

    async def chunks():
        yield payload

    upload = (
        saver.save(uuid.uuid4(), ServiceType.CHAT, "document.pdf", payload)
        if upload_mode == "bytes"
        else saver.save_stream(
            uuid.uuid4(),
            ServiceType.CHAT,
            "document.pdf",
            chunks(),
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_intent_id=uuid.uuid4(),
        )
    )
    task = asyncio.create_task(upload)
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not observed[0].closed
        assert not task.done()
        task.cancel()  # Repeated disconnect/cancellation must not release ownership.
        await asyncio.sleep(0)
        assert not observed[0].closed
        storage.delete_file.assert_not_awaited()
        release.set()
        await asyncio.wait_for(cleanup_started.wait(), 3)
        task.cancel()  # Cleanup must also survive a repeated disconnect.
        await asyncio.sleep(0)
        assert not task.done()
        cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert finished.is_set()
        assert observed[0].closed
        storage._client.put_object.assert_called_once()
        storage.delete_file.assert_awaited_once_with(
            file_key=storage._client.put_object.call_args.kwargs["object_name"]
        )
        repository.add_file_metadata.assert_not_awaited()
        assert "private transport marker" not in caplog.text
    finally:
        release.set()
        cleanup_release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(finished.wait, 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_uncancelled_stream_preserves_success_and_retry_contract(fail_first):
    from io import BytesIO

    payload = b"fixture"
    reads = []

    def put_object(**kwargs):
        reads.append(kwargs["data"].read())
        if fail_first and len(reads) == 1:
            raise TimeoutError("synthetic")

    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._retry_attempts = 2
    storage._retry_backoff = 0
    storage._client = Mock(put_object=Mock(side_effect=put_object))
    with BytesIO(payload) as stream:
        result = await storage.upload_file_stream(
            file_key="attempt-key", stream=stream, length=len(payload)
        )
        assert not stream.closed
    assert result == "s3://fixture/attempt-key"
    assert reads == [payload] * (2 if fail_first else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_mode", ["stream", "bytes"])
async def test_exhausted_upload_compensates_ambiguous_commit_before_metadata(upload_mode, caplog):
    payload = b"fixture"
    objects = {"other-attempt": b"preserve"}

    def put_object(**kwargs):
        objects[kwargs["object_name"]] = kwargs["data"].read()
        raise OSError("PRIVATE_UPLOAD_RESPONSE_BODY")

    async def delete_file(*, file_key):
        objects.pop(file_key, None)

    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._retry_attempts = 3
    storage._retry_backoff = 0
    storage._client = Mock(put_object=Mock(side_effect=put_object))
    storage.delete_file = AsyncMock(side_effect=delete_file)
    repository = Mock(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(),
    )
    saver = FileSaverService(repository, "generated", storage)

    async def chunks():
        yield payload

    with pytest.raises(OSError):
        if upload_mode == "bytes":
            await saver.save(uuid.uuid4(), ServiceType.CHAT, "notes.md", payload)
        else:
            await saver.save_stream(
                uuid.uuid4(),
                ServiceType.CHAT,
                "notes.md",
                chunks(),
                expected_size=len(payload),
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                upload_intent_id=uuid.uuid4(),
            )
    assert storage._client.put_object.call_count == 3
    assert objects == {"other-attempt": b"preserve"}
    storage.delete_file.assert_awaited_once_with(
        file_key=storage._client.put_object.call_args.kwargs["object_name"]
    )
    repository.add_file_metadata.assert_not_awaited()
    assert "PRIVATE_UPLOAD_RESPONSE_BODY" not in caplog.text
