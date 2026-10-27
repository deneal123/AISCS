"""Production storage scans hash bounded chunks, not whole-file download buffers."""

import asyncio
import hashlib
from io import BytesIO
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.infrastructure.storage.scan_metadata_reader import read_scan_metadata
from service.services.files.application.scanning.service import BasicFileScanner


@pytest.mark.asyncio
async def test_scanner_prefers_metadata_reader_without_full_download():
    expected = {"status": "ok", "size": 1, "sha256": "a" * 64}
    storage = SimpleNamespace(
        get_file=AsyncMock(side_effect=AssertionError("whole_download_forbidden")),
        read_file_metadata=AsyncMock(return_value=expected),
    )
    assert await BasicFileScanner(storage).scan("fixture") == expected
    storage.get_file.assert_not_awaited()
    storage.read_file_metadata.assert_awaited_once_with("fixture")


@pytest.mark.asyncio
async def test_local_metadata_reads_real_file_without_read_bytes(tmp_path, monkeypatch):
    body = b"bounded fixture" * 100_000
    storage = LocalFileStorage(tmp_path)
    (tmp_path / "fixture").write_bytes(body)
    monkeypatch.setattr(type(tmp_path), "read_bytes", lambda _self: pytest.fail("unbounded_read"))
    result = await storage.read_file_metadata("fixture")
    assert result == {"status": "ok", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}


@pytest.mark.asyncio
async def test_minio_metadata_uses_bounded_reads_and_releases_response():
    body = b"bounded fixture" * 100_000

    class Response(BytesIO):
        def __init__(self):
            super().__init__(body)
            self.requests = []
            self.released = False

        def read(self, amount=-1):
            assert 0 < amount <= 1024 * 1024
            self.requests.append(amount)
            return super().read(amount)

        def release_conn(self):
            self.released = True

    response = Response()
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._client = SimpleNamespace(get_object=lambda *_args: response)
    result = await storage.read_file_metadata("fixture")
    assert result == {"status": "ok", "size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    assert len(response.requests) >= 3
    assert response.closed and response.released


@pytest.mark.asyncio
async def test_cancelled_minio_read_stops_before_next_chunk_and_releases_after_read():
    entered, proceed, cleaned = Event(), Event(), Event()
    calls = []

    class Response:
        closed = False
        released = False

        def read(self, amount):
            calls.append(amount)
            entered.set()
            assert proceed.wait(5)
            assert not self.closed
            return b"one in-flight chunk"

        def close(self):
            self.closed = True

        def release_conn(self):
            self.released = True
            cleaned.set()

    response = Response()
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._client = SimpleNamespace(get_object=lambda *_args: response)
    task = asyncio.create_task(storage.read_file_metadata("fixture"))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert not response.closed
    finally:
        proceed.set()
        assert await asyncio.wait_for(asyncio.to_thread(cleaned.wait, 2), 3)
        await asyncio.sleep(0)
    assert calls == [1024 * 1024]
    assert response.closed and response.released


@pytest.mark.asyncio
async def test_minio_releases_response_even_if_close_fails():
    released = Event()

    class Response(BytesIO):
        def close(self):
            super().close()
            raise OSError("PRIVATE_SCAN_CLOSE_BODY")

        def release_conn(self):
            released.set()

    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "fixture"
    storage._client = SimpleNamespace(get_object=lambda *_args: Response(b"fixture"))
    assert await BasicFileScanner(storage).scan("fixture") == {
        "status": "error",
        "reason": "unavailable",
    }
    assert released.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunk",
    [None, "PRIVATE_SCAN_BODY", bytearray(b"x"), b"x" * (1024 * 1024 + 1)],
    ids=["missing", "text", "mutable", "oversized"],
)
async def test_invalid_chunk_never_becomes_a_digest(chunk):
    class Response(BytesIO):
        def read(self, _amount):
            return chunk

    response = Response()
    with pytest.raises(ValueError, match="^scan_content_invalid$"):
        await read_scan_metadata(lambda: response)
    assert response.closed
