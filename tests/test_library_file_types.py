"""Library file kind is safe display metadata, never a storage/service mode."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.chat.presentation.routers.chat_api.work_intake import _safe_file
from service.services.files.application.file_saver_service import FileSaverService

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("материалы.TXT", "text"),
        ("notes.md", "text"),
        ("article.PDF", "pdf"),
        ("sheet.csv", "csv"),
        ("sheet.tsv", "tsv"),
        ("legacy.xls", "xls"),
        ("legacy.ppt", "ppt"),
        ("legacy.doc", "doc"),
        ("records.jsonl", "jsonl"),
        ("slides.pptx", "pptx"),
        ("photo.png", "image"),
        ("voice.mp3", "audio"),
        ("video.mp4", "video"),
        ("main.tex", "code"),
        ("references.bib", "code"),
        ("vendor.zip", "archive"),
        ("payload.pdf.exe", "binary"),
        ("unknown", "binary"),
    ],
)
async def test_list_and_intake_return_same_bounded_kind_without_storage_reads(name, expected):
    owner, file_id = uuid4(), uuid4()
    row = SimpleNamespace(
        id=file_id,
        original_name=name,
        file_name="CHAT/private-storage-marker/internal.pdf",
    )
    repository = SimpleNamespace(fetch_user_files_metadata=AsyncMock(return_value=[row]))
    storage = AsyncMock()
    service = FileSaverService(repository, "uploads", storage)
    page = await service.list_chat_library_page(owner, limit=2)
    item = page["items"][0]
    assert item == {
        "file_id": str(file_id),
        "name": name,
        "file_type": expected,
        "availability": "ready",
    }
    assert _safe_file(SimpleNamespace(file_id=file_id), name) == item
    repository.fetch_user_files_metadata.assert_awaited_once_with(
        owner, ServiceType.CHAT, limit=3, offset=0
    )
    assert not storage.mock_calls
    assert "private-storage-marker" not in str(page)


async def test_legacy_kind_uses_only_the_safe_technical_name():
    row = SimpleNamespace(id=uuid4(), original_name=None, file_name="CHAT/private-marker/PDF.PDF")
    repository = SimpleNamespace(fetch_user_files_metadata=AsyncMock(return_value=[row]))
    service = FileSaverService(repository, "uploads", AsyncMock())
    item = (await service.list_chat_library_page(uuid4()))["items"][0]
    assert item["name"] == f"Ранее загруженный файл {str(row.id)[:8]}.pdf"
    assert item["file_type"] == "pdf"
    assert "private-marker" not in str(item)
