"""A stale delivery worker cannot announce a saved Library file as delivered."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owned", "failure"),
    [
        (False, None),
        (True, None),
        (True, "attach"),
        (True, "attach_value"),
        (True, "commit"),
        (True, "invalidate"),
    ],
)
async def test_delivery_compare_and_set_controls_metadata_commit_and_invalidation(
    monkeypatch, caplog, owned, failure
):
    row = {
        "id": uuid.uuid4(),
        "lease_token": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "thread_id": "owned-thread",
        "workspace_id": "owned-workspace",
        "build_id": "opaque-build",
        "artifact_id": "opaque-artifact",
        "role": "pdf",
        "filename": "document.pdf",
        "mime_type": "application/pdf",
        "artifact_size": 4,
        "artifact_sha256": "a" * 64,
    }
    file_id = uuid.uuid4()
    session = AsyncMock()
    download = SimpleNamespace(chunks=lambda: object(), close=AsyncMock())
    files = SimpleNamespace(save_stream=AsyncMock(return_value=SimpleNamespace(file_id=file_id)))
    attach = AsyncMock()
    delivered = AsyncMock(return_value=owned)
    invalidate = AsyncMock()
    defer = AsyncMock()
    marker = "private-finalization-exception-marker"
    if failure == "attach":
        attach.side_effect = RuntimeError(marker)
    elif failure == "attach_value":
        attach.side_effect = ValueError(marker)
    elif failure == "commit":
        session.commit.side_effect = RuntimeError(marker)
    elif failure == "invalidate":
        invalidate.side_effect = RuntimeError(marker)

    @asynccontextmanager
    async def lease(*_args):
        yield asyncio.Event()

    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(
        service.document_publications, "saved_file_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        service, "read_binding", AsyncMock(return_value={"workspace_id": "owned-workspace"})
    )
    monkeypatch.setattr(service, "_agent_ref", lambda *_: {})
    monkeypatch.setattr(service, "_renewing_publication_lease", lease)
    monkeypatch.setattr(service, "_ensure_audited_durable", AsyncMock(return_value="ready"))
    monkeypatch.setattr(
        service, "document_build_status", AsyncMock(return_value={"state": "ready"})
    )
    monkeypatch.setattr(service, "_matching_artifact", lambda *_: True)
    monkeypatch.setattr(service, "stream_document_artifact", AsyncMock(return_value=download))
    monkeypatch.setattr(service.document_publications, "delivered", delivered)
    monkeypatch.setattr(
        service.document_publications, "delivery_completed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(service.document_publications, "defer", defer)
    monkeypatch.setattr(service, "_attach_generated_file", attach)
    monkeypatch.setattr(
        "service.services.chat.application.workspace_event_projection.publish_workspace_invalidation",
        invalidate,
    )

    outcome = await service.deliver_one(
        config=object(),
        pg_connector=object(),
        redis=object(),
        file_service=files,
        session=session,
        row=row,
    )

    download.close.assert_awaited_once()
    files.save_stream.assert_awaited_once()
    delivered.assert_awaited_once_with(
        session,
        job_id=row["id"],
        lease_token=row["lease_token"],
        file_id=file_id,
    )
    assert marker not in caplog.text
    assert marker not in outcome
    if failure and failure != "invalidate":
        assert outcome == "deferred"
        attach.assert_awaited_once_with(session, row, file_id)
        session.rollback.assert_awaited_once()
        defer.assert_awaited_once_with(
            session, job_id=row["id"], lease_token=row["lease_token"], failure_code="unavailable"
        )
        invalidate.assert_not_awaited()
    elif owned:
        defer.assert_not_awaited()
        assert outcome == "delivered"
        attach.assert_awaited_once_with(session, row, file_id)
        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()
        invalidate.assert_awaited_once()
    else:
        defer.assert_not_awaited()
        assert outcome == "deferred"
        attach.assert_not_awaited()
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once()
        invalidate.assert_not_awaited()
