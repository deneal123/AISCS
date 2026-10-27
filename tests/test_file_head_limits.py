"""A head request must never turn into an unbounded storage read."""

from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, True, False, None, 1.5, "16"])
@pytest.mark.parametrize("backend", ["local", "minio"])
async def test_invalid_head_limit_never_reads_storage(tmp_path, limit, backend):
    if backend == "local":
        adapter = LocalFileStorage(tmp_path)
    else:
        adapter = object.__new__(MinioFileStorage)
        adapter._bucket = "fixture"
        adapter._client = Mock()
        adapter._client.get_object.side_effect = AssertionError("unexpected_storage_read")
    with pytest.raises(ValueError, match="^invalid_head_limit$"):
        await adapter.get_file_head("missing-fixture", limit)
    if backend == "minio":
        adapter._client.get_object.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("ranged", [True, False])
@pytest.mark.parametrize("limit", [0, -1, True, False, None, 1.5, "16"])
async def test_service_rejects_invalid_limit_before_ranged_or_legacy_read(limit, ranged):
    adapter = object.__new__(FileSaverService)
    adapter.storage = Mock()
    adapter.storage.get_file_head = AsyncMock(return_value=b"fixture") if ranged else None
    adapter.storage.get_file = AsyncMock(return_value=b"whole-fixture")
    assert await adapter.get_file_head_by_key(file_key="fixture", max_bytes=limit) is None
    adapter.storage.get_file.assert_not_awaited()
    if ranged:
        adapter.storage.get_file_head.assert_not_awaited()


@pytest.mark.asyncio
async def test_minio_head_bounds_response_read_even_if_server_ignores_range():
    adapter = object.__new__(MinioFileStorage)
    adapter._bucket = "fixture"
    adapter._client = Mock()
    response = adapter._client.get_object.return_value
    response.read.side_effect = lambda amount=None: b"0123456789"[:amount]
    assert await adapter.get_file_head("fixture", 4) == b"0123"
    response.read.assert_called_once_with(4)
    response.close.assert_called_once_with()
    response.release_conn.assert_called_once_with()


@pytest.mark.asyncio
async def test_local_head_keeps_a_valid_read_bounded(tmp_path):
    adapter = LocalFileStorage(tmp_path)
    await adapter.upload_file(file_key="fixture", file_data=b"0123456789")
    assert await adapter.get_file_head("fixture", 4) == b"0123"


@pytest.mark.asyncio
@pytest.mark.parametrize("ranged", [True, False])
@pytest.mark.parametrize(
    "payload",
    [
        "PRIVATE-RESPONSE",
        {"private": "PRIVATE-RESPONSE"},
        False,
        bytearray(b"private"),
        memoryview(b"private"),
        None,
    ],
)
async def test_service_prefix_rejects_nonbytes_without_retry(ranged, payload, caplog):
    adapter = object.__new__(FileSaverService)
    adapter.storage = Mock()
    adapter.storage.get_file_head = AsyncMock(return_value=payload) if ranged else None
    adapter.storage.get_file = AsyncMock(return_value=payload)
    assert await adapter.get_file_head_by_key(file_key="fixture", max_bytes=4) is None
    assert "PRIVATE" not in caplog.text
    if ranged:
        adapter.storage.get_file_head.assert_awaited_once_with("fixture", 4)
        adapter.storage.get_file.assert_not_awaited()
    else:
        adapter.storage.get_file.assert_awaited_once_with("fixture")


@pytest.mark.asyncio
@pytest.mark.parametrize("ranged", [True, False])
@pytest.mark.parametrize("payload", [b"", b"ab", b"0123456789"])
async def test_service_prefix_bounds_bytes_and_preserves_empty_file(ranged, payload):
    adapter = object.__new__(FileSaverService)
    adapter.storage = Mock()
    adapter.storage.get_file_head = AsyncMock(return_value=payload) if ranged else None
    adapter.storage.get_file = AsyncMock(return_value=payload)
    assert await adapter.get_file_head_by_key(file_key="fixture", max_bytes=4) == payload[:4]
