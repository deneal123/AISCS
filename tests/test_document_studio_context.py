from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.infrastructure import workspace_client
from service.services.chat.application.documents.context import (
    document_tools_auto_approved,
    validate_document_context,
)
from service.services.chat.domain.documents.context import DocumentContext, document_project_id


def target():
    return {
        "path": "documents/paper",
        "expected_revision": "rev-1",
        "authoring_version": 1,
        "draft_digest": "a" * 64,
        "block_ids": ["intro"],
    }


@pytest.mark.parametrize(
    "path", ["../escape", "/etc/passwd", "a/../b", "a\\b", "C:/secret", "a//b"]
)
def test_document_target_is_relative_and_bounded(path):
    with pytest.raises(ValueError):
        DocumentContext.model_validate({**target(), "path": path})


@pytest.mark.asyncio
async def test_no_document_target_does_not_touch_workspace(monkeypatch):
    read = AsyncMock()
    monkeypatch.setattr(workspace_client, "read_binding", read)
    assert await validate_document_context(None, "thread", "owner", None) is None
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_target_checks_revision_and_blocks(monkeypatch):
    monkeypatch.setattr(
        workspace_client, "read_binding", AsyncMock(return_value={"user_id": "owner"})
    )
    status = AsyncMock(
        return_value={"revision": "rev-1", "authoring_version": 1, "draft_digest": "a" * 64}
    )
    monkeypatch.setattr(workspace_client, "document_project_status", status)
    monkeypatch.setattr(
        workspace_client,
        "document_authoring_state",
        AsyncMock(
            return_value={
                "draft": {
                    "title": "private sentinel",
                    "blocks": [{"block_id": "intro", "text": "source sentinel"}],
                },
            }
        ),
    )
    result = await validate_document_context(None, "thread", "owner", target())
    assert result["project_id"] == document_project_id("owner", "thread", "documents/paper")
    assert result["patch_version"] == 2
    assert document_tools_auto_approved(result)
    assert not document_tools_auto_approved(result, "decline")
    assert "source sentinel" in result["content"]
    with pytest.raises(HTTPException) as failure:
        await validate_document_context(
            None, "thread", "owner", {**target(), "block_ids": ["unknown"]}
        )
    assert failure.value.status_code == 409
    status.return_value["revision"] = "rev-2"
    with pytest.raises(HTTPException) as failure:
        await validate_document_context(None, "thread", "owner", target())
    assert failure.value.status_code == 409


@pytest.mark.asyncio
async def test_foreign_workspace_is_never_read(monkeypatch):
    monkeypatch.setattr(
        workspace_client, "read_binding", AsyncMock(return_value={"user_id": "someone-else"})
    )
    status = AsyncMock()
    monkeypatch.setattr(workspace_client, "document_project_status", status)
    with pytest.raises(HTTPException) as failure:
        await validate_document_context(None, "thread", "owner", target())
    assert failure.value.status_code == 404
    status.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_cannot_read_a_replacement_workspace_generation(monkeypatch):
    monkeypatch.setattr(
        workspace_client,
        "read_binding",
        AsyncMock(return_value={"user_id": "owner", "workspace_id": "new-generation"}),
    )
    status = AsyncMock()
    monkeypatch.setattr(workspace_client, "document_project_status", status)
    with pytest.raises(HTTPException) as failure:
        await validate_document_context(
            None, "thread", "owner", target(), expected_workspace_id="original-generation"
        )
    assert failure.value.status_code == 409
    status.assert_not_awaited()


def test_client_cannot_supply_private_auto_approval_or_project_identity():
    for key, value in (
        ("tools_auto_approved", True),
        ("project_id", "invented"),
        ("patch_version", 2),
    ):
        with pytest.raises(ValueError):
            DocumentContext.model_validate({**target(), key: value})
    assert not document_tools_auto_approved(target())
    assert not document_tools_auto_approved(None)
