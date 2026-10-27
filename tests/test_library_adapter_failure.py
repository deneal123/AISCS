"""Adapter compatibility must not reinterpret an internal failure as pagination."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.services.chat.presentation.routers.chat_api.work_snapshot import library_snapshot
from service.services.files.application.file_saver_service import InvalidLibraryCursor


@pytest.mark.asyncio
async def test_internal_type_error_does_not_retry_without_cursor():
    calls = []

    async def page(owner, *, limit, offset=0, cursor=""):
        calls.append(cursor)
        if cursor:
            raise TypeError("private-adapter-marker")
        return {"items": [{"file_id": "wrong-first-page"}]}

    with pytest.raises(TypeError):
        await library_snapshot(
            SimpleNamespace(list_chat_library_page=page), uuid4(), limit=20, cursor="next-page"
        )
    assert calls == ["next-page"]


@pytest.mark.asyncio
async def test_legacy_adapter_is_called_once_with_supported_arguments():
    calls = []

    async def page(owner, *, limit, offset=0):
        calls.append((limit, offset))
        return {"items": [], "next_offset": 40}

    result = await library_snapshot(
        SimpleNamespace(list_chat_library_page=page),
        uuid4(),
        limit=20,
        offset=20,
        cursor="legacy-ignored",
    )
    assert calls == [(20, 20)]
    assert result["next_offset"] == 40


@pytest.mark.asyncio
async def test_keyword_adapter_keeps_cursor_and_invalid_cursor_is_bounded():
    calls = []

    async def page(owner, **options):
        calls.append(options)
        raise InvalidLibraryCursor("private-cursor-marker")

    with pytest.raises(HTTPException) as error:
        await library_snapshot(
            SimpleNamespace(list_chat_library_page=page),
            uuid4(),
            limit=20,
            offset=10,
            cursor="invalid-cursor",
        )
    assert error.value.status_code == 400
    assert error.value.detail == "invalid_library_cursor"
    assert calls == [{"limit": 20, "offset": 10, "cursor": "invalid-cursor"}]
