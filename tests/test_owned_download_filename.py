"""Owned download names reach the final storage response, not just redirect."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote
from uuid import uuid4

import pytest

from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["report.txt", "материалы статьи (1).md", None])
async def test_owned_download_signer_receives_library_name_not_storage_key(name):
    owner, file_id = uuid4(), uuid4()
    row = SimpleNamespace(
        id=file_id,
        original_name=name,
        file_name="private-key/PRIVATE_STORAGE.pdf",
    )
    repository = SimpleNamespace(fetch_user_file_by_id=AsyncMock(return_value=row))
    signer = AsyncMock(return_value="https://storage.example/owned?signature=opaque")
    service = FileSaverService(repository, "uploads", SimpleNamespace(get_presigned_url=signer))
    result = await service.get_owned_download_url(owner, file_id)
    assert result == "https://storage.example/owned?signature=opaque"
    repository.fetch_user_file_by_id.assert_awaited_once_with(owner, file_id)
    expected = name or f"Ранее загруженный файл {str(file_id)[:8]}.pdf"
    signer.assert_awaited_once_with(
        file_key=row.file_name,
        expiry_sec=3600,
        download_name=expected,
    )
    assert "PRIVATE_STORAGE" not in signer.await_args.kwargs["download_name"]


@pytest.mark.asyncio
async def test_missing_owned_download_cannot_sign_filename_or_source():
    repository = SimpleNamespace(fetch_user_file_by_id=AsyncMock(return_value=None))
    signer = AsyncMock()
    service = FileSaverService(repository, "uploads", SimpleNamespace(get_presigned_url=signer))
    with pytest.raises(ValueError, match="File not found"):
        await service.get_owned_download_url(uuid4(), uuid4())
    signer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.txt", "report.txt"),
        ("материалы статьи (1).md", "материалы статьи (1).md"),
        ("../outside/document.pdf", "document.pdf"),
        ("C:\\private\\report.txt", "report.txt"),
        ('report\r\nInjected: value".pdf', "reportInjected_ value_.pdf"),
        ("name\u202ereport.pdf", "namereport.pdf"),
        ("..", "file"),
        ("CON.txt", "_CON.txt"),
        ("nul.PDF", "_nul.PDF"),
        ("question?.md", "question_.md"),
    ],
)
async def test_minio_signs_ascii_safe_attachment_header_with_utf8_name(name, expected):
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._client = Mock()
    storage._client.presigned_get_object.return_value = "https://storage.example/owned"
    storage._bucket = "fixture"
    storage._presign_expiry = 3600
    storage._public_endpoint = ""
    await storage.get_presigned_url(file_key="PRIVATE_KEY", download_name=name)
    headers = storage._client.presigned_get_object.call_args.kwargs["response_headers"]
    value = headers["response-content-disposition"]
    assert value.startswith('attachment; filename="')
    assert value.isascii() and "\r" not in value and "\n" not in value
    assert "PRIVATE_KEY" not in value
    assert unquote(value.split("filename*=UTF-8''", 1)[1]) == expected


@pytest.mark.asyncio
async def test_long_download_name_stays_bounded_and_keeps_extension():
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._client = Mock()
    storage._client.presigned_get_object.return_value = "https://storage.example/owned"
    storage._bucket = "fixture"
    storage._presign_expiry = 3600
    storage._public_endpoint = ""
    await storage.get_presigned_url(file_key="PRIVATE_KEY", download_name="я" * 1000 + ".pdf")
    value = storage._client.presigned_get_object.call_args.kwargs["response_headers"][
        "response-content-disposition"
    ]
    name = unquote(value.split("filename*=UTF-8''", 1)[1])
    assert len(name.encode()) <= 240 and name.endswith(".pdf")
