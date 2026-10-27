"""PDF-продолжение не заменяет исходное выделение или актуальную пользовательскую версию."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.services.chat.infrastructure.chat_worker.harness import documents
from service.shared.harness_protocol import HarnessFailure
from tests.test_document_studio_context import target


def fixture(monkeypatch):
    saved = target()
    load = AsyncMock(return_value=saved)
    validate = AsyncMock(return_value={**saved, "content": "verified-current-source"})
    monkeypatch.setattr(documents, "load_owned_document_scope", load)
    monkeypatch.setattr(documents, "validate_document_context", validate)
    owner = SimpleNamespace(thread_id="thread", user_id="owner", generation="original")
    return owner, saved, load, validate


@pytest.mark.asyncio
async def test_resume_revalidates_the_original_scope_and_refreshes_content(monkeypatch):
    owner, saved, load, validate = fixture(monkeypatch)
    result = await documents.resume_document_context(
        "connector", "redis", owner, {"document_context": {**saved, "content": "OLD_OR_FORGED"}}
    )
    assert result["content"] == "verified-current-source"
    load.assert_awaited_once_with("connector", owner)
    validate.assert_awaited_once_with(
        "redis", "thread", "owner", saved, expected_workspace_id="original"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changed",
    [dict(block_ids=[]), dict(path="documents/other"), dict(expected_revision="r2")],
)
async def test_changed_scope_is_rejected_before_workspace_read(monkeypatch, changed):
    owner, saved, _, validate = fixture(monkeypatch)
    with pytest.raises(HarnessFailure, match="binding_changed"):
        await documents.resume_document_context(
            "connector", "redis", owner, {"document_context": {**saved, **changed}}
        )
    validate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(404, "project_unavailable"), (409, "binding_changed")])
async def test_current_project_conflict_never_rebases_or_overwrites(monkeypatch, status, code):
    owner, saved, _, validate = fixture(monkeypatch)
    validate.side_effect = HTTPException(status_code=status, detail="PRIVATE")
    with pytest.raises(HarnessFailure, match=code) as raised:
        await documents.resume_document_context(
            "connector", "redis", owner, {"document_context": saved}
        )
    assert "PRIVATE" not in str(raised.value)
