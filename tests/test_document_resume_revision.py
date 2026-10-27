"""A read must not silently rebase accepted semantic blocks onto a newer revision."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.domain.subagents import pdf_generation_runtime as runtime
from service.domain.tools.workspace.client import WorkspaceUnavailable


@pytest.mark.asyncio
@pytest.mark.parametrize("read_revision", [None, "new-revision", "same-revision"])
async def test_resume_requires_lookup_and_source_read_revision_parity(monkeypatch, read_revision):
    checkpoint = object()
    transport = AsyncMock(
        side_effect=[
            {"path": "documents/test", "revision": "same-revision", "checkpoint": {}},
            {"content": "\\begin{document}draft\\end{document}", "revision": read_revision},
        ]
    )
    invalidate = Mock()
    monkeypatch.setattr(runtime, "call", transport)
    monkeypatch.setattr(runtime, "restore_authoring_checkpoint", lambda *args, **kwargs: checkpoint)
    monkeypatch.setattr(
        runtime,
        "current_execution",
        lambda: SimpleNamespace(workspace=SimpleNamespace(invalidate=invalidate)),
    )
    arguments = {
        "source_request_digest": "a" * 64,
        "evidence": SimpleNamespace(digest="b" * 64),
        "citations": None,
    }
    if read_revision == "same-revision":
        result = await runtime.resumable_document_project({}, **arguments)
        assert result[0] == "documents/test"
        assert result[2] is checkpoint
        invalidate.assert_not_called()
    else:
        with pytest.raises(WorkspaceUnavailable) as failure:
            await runtime.resumable_document_project({}, **arguments)
        assert failure.value.code.value == "conflict"
        invalidate.assert_called_once_with(require_read=True)
    assert transport.await_count == 2
