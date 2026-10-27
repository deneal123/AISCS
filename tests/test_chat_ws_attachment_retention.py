"""Disconnect cleanup owns session references, not durable Library objects."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.presentation.ws.chat_ws.temp_files import TempFilesManager


@pytest.mark.asyncio
@pytest.mark.parametrize("references", [None, [], "legacy", {"legacy-id"}])
async def test_disconnect_never_deletes_library_source_and_is_idempotent(references):
    session = {"user_id": str(uuid4()), "_temp_file_ids": references}
    files = SimpleNamespace(delete=AsyncMock())
    owned_file_id = str(uuid4())
    TempFilesManager.register_temp_file_ids(session, [owned_file_id, owned_file_id])
    assert owned_file_id in session["_temp_file_ids"]
    await TempFilesManager.cleanup_temp_files(session, files)
    await TempFilesManager.cleanup_temp_files(session, files)
    files.delete.assert_not_called()
    assert "_temp_file_ids" not in session
    assert session["user_id"]
