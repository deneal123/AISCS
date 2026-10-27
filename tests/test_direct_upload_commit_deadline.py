"""Direct-upload lost acknowledgements need bounded, non-destructive resolution."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.key_value import ServiceType
from service.services.files.application.direct_upload import finalize


@pytest.mark.asyncio
async def test_lost_ack_resolution_times_out_without_deleting_unknown_owned_copy(monkeypatch):
    owner, file_id = uuid4(), uuid4()
    source = f"fixture/{ServiceType.CHAT.value}/pending/{owner.hex}/{file_id.hex}.md"
    timeout = asyncio.timeout
    closed = asyncio.Event()
    deadlines = []
    reads = 0

    def deadline(seconds):
        deadlines.append(seconds)
        return timeout(0.01)

    async def lookup(*_args):
        nonlocal reads
        reads += 1
        if reads == 1:
            return None
        if reads > 2:
            # Cancellation recovery must also preserve an unknown commit.
            raise RuntimeError("private-lookup-marker")
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    offer = {
        "owner": str(owner),
        "mode": ServiceType.CHAT.value,
        "key": source,
        "name": "notes.md",
        "expires_at": time.time() + 60,
    }
    storage = SimpleNamespace(
        build_file_path=lambda *parts: "/".join(parts),
        commit_presigned_upload=AsyncMock(),
    )
    saver = SimpleNamespace(
        folder="fixture",
        storage=storage,
        repository=SimpleNamespace(
            fetch_user_file_by_id=AsyncMock(side_effect=lookup),
            add_file_metadata=AsyncMock(side_effect=RuntimeError("private-commit-marker")),
        ),
        upload_cache=SimpleNamespace(get_json=AsyncMock(return_value=offer)),
        _generate_file_name=lambda _name: "private-copy.md",
        get_presigned_url_by_key=AsyncMock(return_value="https://example.test/private"),
        _delete_uploaded_object=AsyncMock(),
        _cleanup_cancelled_upload=AsyncMock(),
    )
    monkeypatch.setattr(asyncio, "timeout", deadline)
    with pytest.raises(HTTPException) as failure:
        await asyncio.wait_for(finalize(saver, owner, ServiceType.CHAT, file_id, source), 0.2)
    assert failure.value.status_code == 503
    assert failure.value.detail == "Upload unavailable"
    assert closed.is_set()
    assert deadlines == [30]
    assert reads == 2
    saver.repository.add_file_metadata.assert_awaited_once()
    saver._delete_uploaded_object.assert_not_awaited()
    saver._cleanup_cancelled_upload.assert_not_awaited()
