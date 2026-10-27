import asyncio
import hashlib
from unittest.mock import AsyncMock

import pytest

from service.services.files.application.scanning.service import BasicFileScanner


class FakeStorage:
    def __init__(self, data: bytes):
        self.data = data

    async def get_file(self, file_key: str) -> bytes:
        return self.data


@pytest.mark.asyncio
async def test_basic_scanner_computes_sha256():
    s = FakeStorage(b"hello")
    scanner = BasicFileScanner(s)

    res = await scanner.scan("folder/file.jpg")
    assert res["status"] == "ok"
    assert res["size"] == 5
    assert res["sha256"] is not None


@pytest.mark.asyncio
async def test_basic_scanner_handles_missing_getter():
    class NoGetStorage:
        pass

    scanner = BasicFileScanner(NoGetStorage())
    res = await scanner.scan("x")
    assert res["status"] == "skipped"


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, False, 0, "", [], {}])
async def test_invalid_storage_result_is_not_a_successful_scan(data):
    result = await BasicFileScanner(FakeStorage(data)).scan("private-file-key")
    assert result == {"status": "error", "reason": "unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [b"", bytearray()])
async def test_empty_binary_file_has_a_real_digest(data):
    result = await BasicFileScanner(FakeStorage(data)).scan("empty-file")
    assert result == {"status": "ok", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}


@pytest.mark.asyncio
async def test_cancelled_read_is_not_reported_as_a_scan():
    storage = FakeStorage(b"unused")
    storage.get_file = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await BasicFileScanner(storage).scan("cancelled-file")
