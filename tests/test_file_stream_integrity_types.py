"""Malformed artifact streams must not earn a durable Library success."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService


def service():
    repository = SimpleNamespace(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(return_value=SimpleNamespace(id=uuid4())),
    )
    storage = SimpleNamespace(
        build_file_path=lambda *_: "fixture/unique-attempt.pdf",
        upload_file_stream=AsyncMock(return_value="internal://fixture"),
        delete_file=AsyncMock(),
    )
    return FileSaverService(repository, "fixture", storage), repository, storage


async def stream(*items):
    for item in items:
        yield item


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [True, 1.0, 1.9, "1", None])
async def test_expected_size_rejects_coercion_before_repository_or_storage(invalid):
    saver, repository, storage = service()
    with pytest.raises(ValueError, match="^artifact_integrity$"):
        await saver.save_stream(
            uuid4(),
            ServiceType.CHAT,
            "document.pdf",
            stream(b"x"),
            expected_size=invalid,
            expected_sha256=hashlib.sha256(b"x").hexdigest(),
            upload_intent_id=uuid4(),
        )
    repository.fetch_user_file_by_upload_intent.assert_not_awaited()
    repository.add_file_metadata.assert_not_awaited()
    storage.upload_file_stream.assert_not_awaited()
    storage.delete_file.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "private-stream-marker", bytearray(b"extra"), 0])
async def test_non_byte_chunk_is_not_silently_omitted(invalid, caplog):
    saver, repository, storage = service()
    with pytest.raises(ValueError, match="^artifact_integrity$"):
        await saver.save_stream(
            uuid4(),
            ServiceType.CHAT,
            "document.pdf",
            stream(b"x", invalid, b"y"),
            expected_size=2,
            expected_sha256=hashlib.sha256(b"xy").hexdigest(),
            upload_intent_id=uuid4(),
        )
    repository.add_file_metadata.assert_not_awaited()
    storage.upload_file_stream.assert_not_awaited()
    storage.delete_file.assert_not_awaited()
    assert "private-stream-marker" not in caplog.text


@pytest.mark.asyncio
async def test_empty_byte_chunks_preserve_exact_size_hash_and_single_commit():
    saver, repository, storage = service()
    result = await saver.save_stream(
        uuid4(),
        ServiceType.CHAT,
        "document.pdf",
        stream(b"", b"x", b"", b"y", b""),
        expected_size=2,
        expected_sha256=hashlib.sha256(b"xy").hexdigest(),
        upload_intent_id=uuid4(),
    )
    assert result.file_id is not None
    storage.upload_file_stream.assert_awaited_once()
    repository.add_file_metadata.assert_awaited_once()
    storage.delete_file.assert_not_awaited()
