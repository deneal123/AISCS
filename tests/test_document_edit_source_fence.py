from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents import edits as edits
from service.services.chat.presentation.routers.chat_api.workspace.contracts import (
    DocumentDraftEditRequest,
)


def payload(source_digest=None):
    return DocumentDraftEditRequest(
        path="documents/paper",
        draft={"title": "Private text"},
        authoring_version=0,
        draft_digest=None,
        expected_revision="r1",
        expected_source_digest=source_digest,
        fence=1,
    )


@pytest.mark.asyncio
async def test_editor_checks_the_pinned_source_digest_before_reading_or_rendering(monkeypatch):
    client = SimpleNamespace(
        document_project_status=AsyncMock(
            return_value={
                "revision": "r1",
                "authoring_version": 0,
                "draft_digest": None,
                "source_digest": "b" * 64,
            }
        ),
        read_file=AsyncMock(),
    )
    renderer = AsyncMock()
    monkeypatch.setattr(edits, "_client", renderer)
    with pytest.raises(HTTPException) as failure:
        await edits.render_owned_edit(client, {}, payload("a" * 64), object())
    assert failure.value.status_code == 409
    assert failure.value.detail == "source_changed"
    client.read_file.assert_not_awaited()
    renderer.assert_not_called()


@pytest.mark.parametrize("pinned", [None, "a" * 64])
@pytest.mark.asyncio
async def test_render_carries_the_original_source_digest_to_the_atomic_writer(monkeypatch, pinned):
    project = {
        "revision": "r1",
        "authoring_version": 0,
        "draft_digest": None,
        "source_digest": "a" * 64,
    }
    client = SimpleNamespace(
        document_project_status=AsyncMock(return_value=project),
        read_file=AsyncMock(return_value={"content": "main text", "truncated": False}),
    )
    rpc = SimpleNamespace(
        request_json=AsyncMock(
            return_value={
                "files": {"main.tex": "new text"},
                "authoring_version": 1,
                "draft_digest": "c" * 64,
                # A renderer response is not allowed to rebase the publication fence.
                "expected_source_digest": "d" * 64,
            }
        )
    )
    monkeypatch.setattr(edits, "_client", lambda *_: rpc)
    result = await edits.render_owned_edit(client, {}, payload(pinned), object())
    assert result["expected_source_digest"] == "a" * 64
    assert result["files"] == {"main.tex": "new text"}
