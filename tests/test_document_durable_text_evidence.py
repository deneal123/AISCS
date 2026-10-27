"""Cache expiry must not truncate a valid owned Markdown source to chat-context size."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.context.attachment_evidence import (
    owner_checked_attachments,
)


@pytest.mark.asyncio
async def test_long_cyrillic_markdown_survives_cache_expiry_without_parser(monkeypatch):
    source = "Исходный проверяемый материал.\n" * 1000 + "Последний раздел источника."
    owner, file_id = uuid4(), uuid4()
    row = SimpleNamespace(
        original_name="materials.md", file_name="owned/source.md", content_sha256="a" * 64
    )
    files = SimpleNamespace(
        repository=SimpleNamespace(fetch_user_file_by_id=AsyncMock(return_value=row)),
        get_file_by_key=AsyncMock(return_value=b"\xef\xbb\xbf" + source.encode()),
    )
    parser = AsyncMock(side_effect=AssertionError("plaintext_must_not_be_truncated_by_parser"))
    monkeypatch.setattr(
        "service.services.chat.infrastructure.media.opendataloader_parser.OpenDataLoaderParser.parse",
        parser,
    )
    evidence = await owner_checked_attachments(
        files,
        user_id=str(owner),
        file_ids=[str(file_id)],
        attachments=[{"file_id": str(file_id), "name": "browser-name.md"}],
        redis=None,
    )
    assert len(evidence) == 1
    assert evidence[0]["content"] == source
    assert len(evidence[0]["content"]) > 5000
    parser.assert_not_called()
