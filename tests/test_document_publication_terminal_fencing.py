"""Only an owned SQL transition can produce a terminal delivery outcome."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize(
    ("stage", "failure_code"),
    [
        ("binding", "workspace_expired"),
        ("audit", "artifact_invalid"),
        ("status", "artifact_mismatch"),
        ("missing", "artifact_mismatch"),
        ("expired", "workspace_expired"),
        ("saved_file", "artifact_mismatch"),
    ],
)
async def test_terminal_outcome_requires_the_current_outbox_lease(
    monkeypatch, caplog, stage, failure_code, owned
):
    row = {
        "id": uuid.uuid4(),
        "lease_token": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "thread_id": "owned-thread",
        "workspace_id": "owned-workspace",
        "build_id": "build",
        "artifact_id": "artifact",
    }
    session, files = AsyncMock(), AsyncMock()
    defer = AsyncMock(return_value=owned)
    saved = AsyncMock(return_value=None)
    binding = AsyncMock(return_value={"workspace_id": row["workspace_id"]})
    audit = AsyncMock(return_value="ready")
    download = AsyncMock(side_effect=service.DocumentArtifactMissing())
    if stage == "binding":
        binding.return_value = None
    elif stage == "audit":
        audit.return_value = "artifact_invalid"
    elif stage == "expired":
        binding.side_effect = service.WorkspaceGone("private-lease-failure-marker")
    elif stage == "saved_file":
        saved.side_effect = service.document_publications.PublicationArtifactMismatch()

    @asynccontextmanager
    async def lease(*_args):
        yield asyncio.Event()

    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service.document_publications, "saved_file_id", saved)
    monkeypatch.setattr(service.document_publications, "defer", defer)
    monkeypatch.setattr(service, "read_binding", binding)
    monkeypatch.setattr(service, "_agent_ref", lambda *_: {})
    monkeypatch.setattr(service, "_renewing_publication_lease", lease)
    monkeypatch.setattr(service, "_ensure_audited_durable", audit)
    monkeypatch.setattr(
        service, "document_build_status", AsyncMock(return_value={"state": "ready"})
    )
    monkeypatch.setattr(service, "_matching_artifact", lambda *_: stage != "status")
    monkeypatch.setattr(service, "stream_document_artifact", download)
    attach = AsyncMock()
    monkeypatch.setattr(service, "_attach_generated_file", attach)
    invalidation = AsyncMock()
    monkeypatch.setattr(
        "service.services.chat.application.workspace_event_projection.publish_workspace_invalidation",
        invalidation,
    )
    result = await service.deliver_one(
        config=object(),
        pg_connector=object(),
        redis=object(),
        file_service=files,
        session=session,
        row=row,
    )
    assert result == ("terminal" if owned else "deferred")
    defer.assert_awaited_once_with(
        session,
        job_id=row["id"],
        lease_token=row["lease_token"],
        failure_code=failure_code,
        terminal=True,
    )
    if not owned:
        assert session.rollback.await_count >= 1
    session.commit.assert_not_awaited()
    attach.assert_not_awaited()
    invalidation.assert_not_awaited()
    files.save_stream.assert_not_awaited()
    assert "private-lease-failure-marker" not in caplog.text
