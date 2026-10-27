"""Native storage reads are bounded, streaming and cancellation-safe."""

import asyncio
import io
import threading
from unittest.mock import Mock

import pytest

from service.infrastructure.storage.bounded_download import CHUNK_BYTES, copy_bounded
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.infrastructure.storage.minio_file_storage import MinioFileStorage


def minio_with(body):
    storage = object.__new__(MinioFileStorage)
    storage._bucket = "fixture-private-bucket"
    response = Mock(wraps=io.BytesIO(body))
    response.release_conn = Mock()
    storage._client = Mock()
    storage._client.get_object.return_value = response
    return storage, response


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["local", "minio"])
@pytest.mark.parametrize(
    "body",
    [b"", b"binary\x00\xff", b"x" * (CHUNK_BYTES * 3 + 1)],
    ids=["empty", "binary", "multichunk"],
)
async def test_bounded_read_keeps_caller_open_and_exact_bytes(tmp_path, adapter, body):
    if adapter == "local":
        storage, response = LocalFileStorage(tmp_path), None
        await storage.upload_file(file_key="fixture.blob", file_data=body)
    else:
        storage, response = minio_with(body)
    target = io.BytesIO(b"prefix:")
    target.seek(0, 2)
    size = await storage.download_file_stream(
        file_key="fixture.blob", target=target, max_bytes=len(body)
    )
    assert size == len(body)
    assert target.getvalue() == b"prefix:" + body
    assert not target.closed
    if response is not None:
        storage._client.get_object.assert_called_once_with(
            storage._bucket,
            "fixture.blob",
            **({"offset": 0, "length": len(body) + 1} if body else {}),
        )
        assert all(0 < call.args[0] <= CHUNK_BYTES for call in response.read.call_args_list)
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["local", "minio"])
@pytest.mark.parametrize("limit", [0, 3, CHUNK_BYTES])
async def test_oversized_object_cannot_publish_truncated_success(tmp_path, adapter, limit):
    body = b"x" * (limit + 1)
    if adapter == "local":
        storage, response = LocalFileStorage(tmp_path), None
        await storage.upload_file(file_key="fixture.blob", file_data=body)
    else:
        storage, response = minio_with(body)
    target = io.BytesIO()
    with pytest.raises(ValueError, match="^storage_download_limit_exceeded$"):
        await storage.download_file_stream(file_key="fixture.blob", target=target, max_bytes=limit)
    assert len(target.getvalue()) <= limit
    assert not target.closed
    if response is not None:
        response.close.assert_called_once()
        response.release_conn.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["local", "minio"])
@pytest.mark.parametrize("limit", [-1, True, False, 1.5, "1", None, 2**63 - 1])
async def test_bad_limit_never_starts_io(tmp_path, adapter, limit):
    storage = LocalFileStorage(tmp_path) if adapter == "local" else minio_with(b"")[0]
    target = Mock()
    with pytest.raises(ValueError, match="^storage_download_limit_invalid$"):
        await storage.download_file_stream(file_key="missing", target=target, max_bytes=limit)
    target.write.assert_not_called()
    if adapter == "minio":
        storage._client.get_object.assert_not_called()


@pytest.mark.parametrize("chunk", [None, "private body", bytearray(b"x"), b"too large"])
def test_non_binary_or_overdelivering_reader_is_rejected(chunk):
    target = io.BytesIO()
    with pytest.raises(ValueError, match="^storage_download_stream_invalid$"):
        copy_bounded(Mock(read=Mock(return_value=chunk)), target, 1)
    assert target.getvalue() == b""


def test_partial_local_write_is_not_a_success():
    with pytest.raises(OSError, match="^storage_download_write_incomplete$"):
        copy_bounded(io.BytesIO(b"abc"), Mock(write=Mock(return_value=2)), 3)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_minio_failure_always_releases_response(failure):
    storage, response = minio_with(b"abc")
    if failure:
        response.read.side_effect = OSError("private-sdk-body")
    else:
        response.close.side_effect = OSError("private-close-body")
    with pytest.raises(OSError):
        await storage.download_file_stream(
            file_key="fixture.blob", target=io.BytesIO(), max_bytes=3
        )
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["local", "minio"])
@pytest.mark.parametrize("failure", [False, True])
async def test_repeated_cancellation_waits_for_exact_reader(
    tmp_path, adapter, failure, monkeypatch, caplog
):
    entered, release = threading.Event(), threading.Event()
    storage = LocalFileStorage(tmp_path)
    await storage.upload_file(file_key="fixture.blob", file_data=b"abc")
    response = None
    if adapter == "minio":
        storage, response = minio_with(b"abc")
    target = io.BytesIO()
    original_write = target.write

    def held_write(chunk):
        entered.set()
        assert release.wait(3)
        assert not target.closed
        if failure:
            raise OSError("private-reader-marker")
        return original_write(chunk)

    monkeypatch.setattr(target, "write", held_write)
    task = asyncio.create_task(
        storage.download_file_stream(file_key="fixture.blob", target=target, max_bytes=3)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done(), "reader still owns the stream after request cancellation"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    assert not target.closed
    if response is not None:
        response.close.assert_called_once()
        response.release_conn.assert_called_once()
    assert "private-reader-marker" not in caplog.text
