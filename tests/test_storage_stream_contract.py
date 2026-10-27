"""Storage adapters reject malformed declared lengths before touching a stream."""

from io import BytesIO
from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.infrastructure.storage.minio_file_storage import MinioFileStorage


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["local", "minio"])
@pytest.mark.parametrize("length", [-1, True, False, 1.5, "1", None])
async def test_invalid_length_never_seeks_writes_or_retries(tmp_path, adapter, length, caplog):
    stream = Mock()
    stream.read.return_value = b""
    storage = LocalFileStorage(tmp_path)
    if adapter == "minio":
        storage = object.__new__(MinioFileStorage)
        storage._retry_attempts = 3
        storage._retry_backoff = 0
        storage._bucket = "fixture"
        storage._upload_stream_once = AsyncMock()
    with pytest.raises(ValueError, match="^storage_stream_invalid$"):
        await storage.upload_file_stream(file_key="fixture.txt", stream=stream, length=length)
    stream.seek.assert_not_called()
    stream.read.assert_not_called()
    assert list(tmp_path.iterdir()) == []
    if adapter == "minio":
        storage._upload_stream_once.assert_not_awaited()
    assert "fixture.txt" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk", ["private-chunk", bytearray(b"x"), b"oversized"])
async def test_local_reader_cannot_write_invalid_or_oversized_chunk(tmp_path, chunk):
    storage = LocalFileStorage(tmp_path)
    stream = Mock()
    stream.read.side_effect = [chunk, b""]
    with pytest.raises(ValueError, match="^storage_stream_invalid$"):
        await storage.upload_file_stream(file_key="fixture.txt", stream=stream, length=1)
    assert (tmp_path / "fixture.txt").read_bytes() == b""
    assert stream.read.call_args_list == [((1,),)]


@pytest.mark.asyncio
async def test_zero_length_local_upload_is_explicit_empty_file(tmp_path):
    storage = LocalFileStorage(tmp_path)
    stream = BytesIO(b"")
    await storage.upload_file_stream(file_key="empty.txt", stream=stream, length=0)
    assert await storage.get_file("empty.txt") == b""
    assert not stream.closed
