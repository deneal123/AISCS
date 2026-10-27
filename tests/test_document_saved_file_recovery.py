"""Persisted audited Library files survive loss of the temporary workspace."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


def arrange(monkeypatch, *, state="pending_delivery", audited=True, candidate=True, mismatch=None):
    row = {
        "id": uuid.uuid4(),
        "lease_token": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "thread_id": "owned-thread",
        "workspace_id": "expired-workspace",
        "build_id": "opaque-build",
        "artifact_id": "opaque-artifact",
        "role": "pdf",
        "filename": "document.pdf",
        "mime_type": "application/pdf",
        "artifact_size": 4,
        "artifact_sha256": "a" * 64,
        "source_digest": "b" * 64,
        "assistant_message_id": 1,
        "status": state,
    }
    file_id = uuid.uuid4()
    file = {
        "id": file_id,
        "mode": "CHAT",
        "original_name": "document.pdf",
        "content_sha256": "a" * 64,
        "audit_passed": audited,
    }
    if mismatch:
        file[mismatch] = "not-the-expected-value"
    result = SimpleNamespace(
        mappings=lambda: SimpleNamespace(first=lambda: file if candidate else None)
    )
    session = AsyncMock()
    session.execute.return_value = result
    settled, attach = AsyncMock(), AsyncMock()
    delivered = AsyncMock(return_value=True)
    defer = AsyncMock(return_value=True)
    invalidation = AsyncMock()
    monkeypatch.setattr(service, "_settle_pending_audit", settled)
    monkeypatch.setattr(service, "read_binding", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "_ensure_audited_durable", AsyncMock())
    monkeypatch.setattr(service, "stream_document_artifact", AsyncMock())
    monkeypatch.setattr(service, "_attach_generated_file", attach)
    monkeypatch.setattr(service.document_publications, "delivered", delivered)
    monkeypatch.setattr(
        service.document_publications, "delivery_completed", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(service.document_publications, "defer", defer)
    monkeypatch.setattr(
        "service.services.chat.application.workspace_event_projection.publish_workspace_invalidation",
        invalidation,
    )
    return SimpleNamespace(
        row=row,
        file_id=file_id,
        session=session,
        settled=settled,
        attach=attach,
        delivered=delivered,
        defer=defer,
        invalidation=invalidation,
        files=SimpleNamespace(save_stream=AsyncMock()),
    )


async def deliver(setup):
    return await service.deliver_one(
        config=object(),
        pg_connector=object(),
        redis=object(),
        file_service=setup.files,
        session=setup.session,
        row=setup.row,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending_delivery", "pending_audit"])
async def test_owned_audited_file_finalizes_without_workspace_or_new_calls(monkeypatch, state):
    setup = arrange(monkeypatch, state=state)
    assert await deliver(setup) == "delivered"
    setup.settled.assert_awaited_once()
    setup.delivered.assert_awaited_once_with(
        setup.session,
        job_id=setup.row["id"],
        lease_token=setup.row["lease_token"],
        file_id=setup.file_id,
    )
    setup.attach.assert_awaited_once_with(setup.session, setup.row, setup.file_id)
    setup.session.commit.assert_awaited_once()
    setup.defer.assert_not_awaited()
    service.read_binding.assert_not_awaited()
    service._ensure_audited_durable.assert_not_awaited()
    service.stream_document_artifact.assert_not_awaited()
    setup.files.save_stream.assert_not_awaited()
    setup.invalidation.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_loss_prevents_saved_file_announcement(monkeypatch):
    setup = arrange(monkeypatch)
    setup.delivered.return_value = False
    assert await deliver(setup) == "deferred"
    setup.attach.assert_not_awaited()
    setup.invalidation.assert_not_awaited()
    setup.session.rollback.assert_awaited_once()
    setup.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_replay_does_not_touch_projection_or_publish_again(monkeypatch):
    setup = arrange(monkeypatch)
    setup.delivered.return_value = False
    monkeypatch.setattr(
        service.document_publications, "delivery_completed", AsyncMock(return_value=True)
    )
    assert await deliver(setup) == "delivered"
    setup.attach.assert_not_awaited()
    setup.invalidation.assert_not_awaited()
    setup.session.rollback.assert_awaited_once()
    service.read_binding.assert_not_awaited()


@pytest.mark.asyncio
async def test_authoritative_completed_row_has_no_lease_and_is_safe_to_replay(monkeypatch):
    setup = arrange(monkeypatch)
    setup.row.update(status="delivered", lease_token=None)
    monkeypatch.setattr(
        service.document_publications, "delivery_completed", AsyncMock(return_value=True)
    )
    assert await deliver(setup) == "delivered"
    setup.delivered.assert_not_awaited()
    setup.attach.assert_not_awaited()
    setup.invalidation.assert_not_awaited()
    service.read_binding.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [False, True])
async def test_unclaimed_pending_row_does_not_start_or_reschedule_work(monkeypatch, candidate):
    setup = arrange(monkeypatch, candidate=candidate)
    setup.row["lease_token"] = None
    assert await deliver(setup) == "deferred"
    setup.delivered.assert_not_awaited()
    setup.attach.assert_not_awaited()
    setup.defer.assert_not_awaited()
    service.read_binding.assert_not_awaited()


@pytest.mark.asyncio
async def test_nullable_lease_cannot_change_persistence_or_retry_state():
    session = AsyncMock()
    assert not await service.document_publications.delivered(
        session, job_id=uuid.uuid4(), lease_token=None, file_id=uuid.uuid4()
    )
    assert not await service.document_publications.defer(
        session, job_id=uuid.uuid4(), lease_token=None, failure_code="unavailable"
    )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "unproven_audit"])
async def test_missing_or_unaudited_file_does_not_bypass_workspace_audit(monkeypatch, case):
    setup = arrange(monkeypatch, state="pending_audit", audited=False, candidate=case != "missing")
    assert await deliver(setup) == "terminal"
    setup.delivered.assert_not_awaited()
    setup.attach.assert_not_awaited()
    setup.defer.assert_awaited_once_with(
        setup.session,
        job_id=setup.row["id"],
        lease_token=setup.row["lease_token"],
        failure_code="workspace_expired",
        terminal=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["mode", "original_name", "content_sha256"])
async def test_incompatible_saved_file_is_terminal_without_overwrite(monkeypatch, field):
    setup = arrange(monkeypatch, mismatch=field)
    assert await deliver(setup) == "terminal"
    setup.delivered.assert_not_awaited()
    setup.files.save_stream.assert_not_awaited()
    setup.defer.assert_awaited_once_with(
        setup.session,
        job_id=setup.row["id"],
        lease_token=setup.row["lease_token"],
        failure_code="artifact_mismatch",
        terminal=True,
    )
    service.read_binding.assert_not_awaited()


@pytest.mark.asyncio
async def test_saved_file_lookup_outage_is_deferred_not_expired(monkeypatch, caplog):
    setup = arrange(monkeypatch)
    marker = "private-library-read-error"
    setup.session.execute.side_effect = RuntimeError(marker)
    assert await deliver(setup) == "deferred"
    setup.session.rollback.assert_awaited_once()
    service.read_binding.assert_not_awaited()
    assert marker not in caplog.text
    assert setup.defer.await_args.kwargs["failure_code"] == "unavailable"
