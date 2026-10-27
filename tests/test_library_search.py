"""Поиск библиотеки выполняется до ограничения страницы и только для владельца."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from service.models.key_value import ServiceType
from service.services.chat.presentation.routers.chat_api.work_snapshot import library_snapshot
from service.services.files.application.file_saver_service import FileSaverService
from service.services.files.persistence.file_repository import FileRepository


@pytest.mark.asyncio
async def test_search_is_forwarded_with_bounded_page_and_safe_metadata():
    owner = uuid4()
    rows = [
        SimpleNamespace(id=uuid4(), original_name=f"Отчёт {n}.pdf", created_at=None)
        for n in range(3)
    ]
    repository = SimpleNamespace(fetch_user_files_metadata=AsyncMock(return_value=rows))
    service = FileSaverService(repository, "uploads", AsyncMock())
    result = await library_snapshot(service, owner, limit=2, offset=10, search="Отчёт")
    repository.fetch_user_files_metadata.assert_awaited_once_with(
        owner, ServiceType.CHAT, limit=3, offset=10, search="Отчёт"
    )
    assert len(result["items"]) == 2
    assert result["next_offset"] == 12
    assert result["items"][0]["name"] == "Отчёт 0.pdf"


@pytest.mark.asyncio
async def test_search_is_owner_scoped_literal_case_insensitive_and_paginated():
    owner = uuid4()
    session = AsyncMock()
    session.execute.return_value = Mock()
    session.execute.return_value.scalars.return_value.all.return_value = []
    await FileRepository(connector=Mock()).fetch_user_files_metadata(
        owner, ServiceType.CHAT, session=session, search="Отчёт_100%", offset=10, limit=11
    )
    statement = session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "user_file.user_id =" in sql and "user_file.mode =" in sql
    assert " ILIKE " in sql and "ESCAPE" in sql
    assert "ORDER BY" in sql and "LIMIT" in sql and "OFFSET" in sql
    assert owner in statement.params.values()
    assert "Отчёт/_100/%" in statement.params.values()
    assert 10 in statement.params.values() and 11 in statement.params.values()
