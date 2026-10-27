"""Lease loss fences new audit calls, stream consumption and Library persistence."""

import asyncio
import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import lease as lease_service
from service.services.chat.application.documents.publication import service as service
from service.services.files.application.file_saver_service import FileSaverService
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


def arrange(monkeypatch, *, initial_loss=False, loss_stage=None):
    lost = asyncio.Event()
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
        "artifact_size": 6,
        "artifact_sha256": hashlib.sha256(b"onetwo").hexdigest(),
    }
    repository = SimpleNamespace(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())),
    )

    async def upload(**kwargs):
        assert kwargs["stream"].read() == b"onetwo"
        if loss_stage == "upload":
            lost.set()
        return "internal://object"

    storage = SimpleNamespace(
        build_file_path=lambda *_: "uploads/CHAT/opaque.pdf",
        upload_file_stream=AsyncMock(side_effect=upload),
        delete_file=AsyncMock(),
    )
    files = FileSaverService(repository, "uploads", storage)

    async def chunks():
        yield b"one"
        if loss_stage == "read":
            lost.set()
        yield b"two"

    download = SimpleNamespace(chunks=chunks, close=AsyncMock())

    @asynccontextmanager
    async def lease(*_args):
        if initial_loss:
            lost.set()
        yield lost

    audit = AsyncMock(return_value="ready")
    connector_session = AsyncMock()
    connector = SimpleNamespace(get_session_context=lambda: connector_session)
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(
        service.document_publications, "saved_file_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        service, "read_binding", AsyncMock(return_value={"workspace_id": "owned-workspace"})
    )
    monkeypatch.setattr(service, "_agent_ref", lambda *_: {})
    monkeypatch.setattr(service, "_renewing_publication_lease", lease)
    monkeypatch.setattr(service, "_ensure_audited_durable", audit)
    monkeypatch.setattr(
        service, "document_build_status", AsyncMock(return_value={"state": "ready"})
    )
    monkeypatch.setattr(service, "_matching_artifact", lambda *_: True)
    monkeypatch.setattr(service, "stream_document_artifact", AsyncMock(return_value=download))
    renew = AsyncMock(return_value=True)
    if loss_stage == "renew":
        renew.side_effect = [True, False]
    monkeypatch.setattr(service.document_publications, "renew", renew)
    monkeypatch.setattr(service.document_publications, "delivered", AsyncMock(return_value=True))
    monkeypatch.setattr(service.document_publications, "defer", AsyncMock())
    monkeypatch.setattr(service, "_attach_generated_file", AsyncMock())
    monkeypatch.setattr(
        "service.services.chat.application.workspace_event_projection.publish_workspace_invalidation",
        AsyncMock(),
    )
    return SimpleNamespace(
        row=row,
        lost=lost,
        audit=audit,
        repository=repository,
        storage=storage,
        files=files,
        download=download,
        connector=connector,
        session=AsyncMock(),
    )


async def deliver(setup):
    return await service.deliver_one(
        config=object(),
        pg_connector=setup.connector,
        redis=object(),
        file_service=setup.files,
        session=setup.session,
        row=setup.row,
    )


@pytest.mark.asyncio
async def test_expired_lease_does_not_start_a_new_paid_audit(monkeypatch):
    setup = arrange(monkeypatch, initial_loss=True)
    assert await deliver(setup) == "deferred"
    setup.audit.assert_not_awaited()
    service.stream_document_artifact.assert_not_awaited()
    setup.repository.add_file_metadata.assert_not_awaited()
    service.document_publications.defer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["read", "upload", "renew"])
async def test_lease_loss_does_not_create_a_library_row(monkeypatch, stage):
    setup = arrange(monkeypatch, loss_stage=stage)
    assert await deliver(setup) == "deferred"
    setup.repository.add_file_metadata.assert_not_awaited()
    setup.download.close.assert_awaited_once()
    service.document_publications.delivered.assert_not_awaited()
    service.document_publications.defer.assert_not_awaited()
    setup.session.rollback.assert_awaited_once()
    if stage == "read":
        setup.storage.upload_file_stream.assert_not_awaited()
        setup.storage.delete_file.assert_not_awaited()
    else:
        setup.storage.upload_file_stream.assert_awaited_once()
        setup.storage.delete_file.assert_awaited_once_with(file_key="uploads/CHAT/opaque.pdf")


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["expired", "transport", "commit", "timeout"])
async def test_initial_renewal_is_required_and_fail_closed(monkeypatch, caplog, reason):
    row = {"id": uuid.uuid4(), "lease_token": uuid.uuid4()}
    session = AsyncMock()
    connector = SimpleNamespace(get_session_context=lambda: session)
    renew = AsyncMock(return_value=reason != "expired")
    marker = "private-publication-lease-exception"
    if reason == "transport":
        renew.side_effect = RuntimeError(marker)
    elif reason == "commit":
        session.__aenter__.return_value.commit.side_effect = RuntimeError(marker)
    elif reason == "timeout":

        async def blocked(*_args, **_kwargs):
            await asyncio.Event().wait()

        renew.side_effect = blocked
        monkeypatch.setattr(lease_service, "_RENEW_TIMEOUT", 0.02)
    monkeypatch.setattr(service.document_publications, "renew", renew)
    async with lease_service.renewing_publication_lease(connector, row) as lost:
        assert renew.await_count == 1  # No work is admitted before the first renewal.
        assert lost.is_set()
    assert marker not in caplog.text


@pytest.mark.asyncio
async def test_heartbeat_failure_signals_loss_and_is_joined(monkeypatch):
    session = AsyncMock()
    connector = SimpleNamespace(get_session_context=lambda: session)
    renew = AsyncMock(side_effect=[True, False])
    monkeypatch.setattr(service.document_publications, "renew", renew)
    monkeypatch.setattr(lease_service, "_HEARTBEAT_INTERVAL", 0.01)
    before = asyncio.all_tasks()
    async with lease_service.renewing_publication_lease(
        connector, {"id": uuid.uuid4(), "lease_token": uuid.uuid4()}
    ) as lost:
        assert not lost.is_set()
        await asyncio.wait_for(lost.wait(), timeout=1)
    assert renew.await_count == 2
    assert asyncio.all_tasks() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["lease_lost", "cancelled"])
async def test_blocked_download_is_cancelled_closed_and_joined(reason):
    lost, reading, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def chunks():
        try:
            yield b"one"
            reading.set()
            await asyncio.Event().wait()
        finally:
            closed.set()

    before = asyncio.all_tasks()

    async def consume():
        return [chunk async for chunk in lease_service.lease_checked_chunks(chunks(), lost)]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(reading.wait(), timeout=1)
    if reason == "lease_lost":
        lost.set()
        failure = lease_service.PublicationLeaseLost
    else:
        task.cancel()
        failure = asyncio.CancelledError
    with pytest.raises(failure):
        await asyncio.wait_for(task, timeout=1)
    assert closed.is_set()
    assert asyncio.all_tasks() == before


@pytest.mark.asyncio
async def test_loss_at_end_of_source_cannot_pass_integrity_and_publish():
    lost = asyncio.Event()

    async def chunks():
        yield b"one"
        lost.set()

    with pytest.raises(lease_service.PublicationLeaseLost):
        _ = [chunk async for chunk in lease_service.lease_checked_chunks(chunks(), lost)]


@pytest.mark.asyncio
async def test_accepted_audit_usage_is_not_cancelled_on_lease_loss(monkeypatch):
    setup = arrange(monkeypatch)
    accepted, settled = asyncio.Event(), asyncio.Event()

    async def audit(**_kwargs):
        accepted.set()
        setup.lost.set()
        await asyncio.sleep(0)
        settled.set()
        return "ready"

    setup.audit.side_effect = audit
    assert await deliver(setup) == "deferred"
    assert accepted.is_set() and settled.is_set()
    setup.repository.add_file_metadata.assert_not_awaited()
    service.document_publications.defer.assert_not_awaited()


@pytest.mark.asyncio
async def test_lease_loss_during_preflight_prevents_the_actual_provider_call(monkeypatch):
    session = AsyncMock()
    audit = AsyncMock()
    guard = AsyncMock(side_effect=lease_service.PublicationLeaseLost())
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(
        service,
        "document_build_status",
        AsyncMock(
            return_value={
                "state": "visual_pending",
                "build_id": "opaque-build",
                "source_digest": "a" * 64,
                "artifacts": [
                    {
                        "artifact_id": "artifact",
                        "sha256": "b" * 64,
                        "size": 4,
                        "mime_type": "application/pdf",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        service.document_audit_attempts, "attestation_pending", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(return_value={"id": uuid.uuid4(), "state": "started", "may_execute": True}),
    )
    monkeypatch.setattr(service, "audit_document", audit)
    monkeypatch.setattr(service, "_charge_visual_audit", AsyncMock())
    with pytest.raises(lease_service.PublicationLeaseLost):
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=session,
            ref={},
            row={
                "build_id": "opaque-build",
                "source_digest": "a" * 64,
                "artifact_id": "artifact",
                "artifact_sha256": "b" * 64,
                "artifact_size": 4,
                "mime_type": "application/pdf",
            },
            before_audit=guard,
        )
    guard.assert_awaited_once()
    audit.assert_not_awaited()
    service._charge_visual_audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_stream_keeps_upload_intent_and_one_library_row(monkeypatch):
    setup = arrange(monkeypatch)
    assert await deliver(setup) == "delivered"
    setup.repository.add_file_metadata.assert_awaited_once()
    setup.storage.delete_file.assert_not_awaited()
    setup.download.close.assert_awaited_once()
    service.document_publications.renew.assert_awaited()
    metadata = setup.repository.add_file_metadata.await_args.args[0]
    assert metadata.upload_intent_id == uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"gpthub-document:{setup.row['user_id']}:{setup.row['build_id']}:"
        f"{setup.row['artifact_id']}:{setup.row['role']}",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_chunk", ["private-source-marker", b"oversized-source"])
async def test_rejected_artifact_closes_source_and_lease_watcher_before_return(
    monkeypatch, invalid_chunk, caplog
):
    setup = arrange(monkeypatch)
    closed = asyncio.Event()
    wrappers = []
    original = service.lease_checked_chunks

    async def source():
        try:
            yield b"one"
            yield invalid_chunk
            raise AssertionError("rejected_source_was_read_again")
        finally:
            closed.set()

    # Retain the generator explicitly: resource cleanup must not rely on GC.
    upstream = source()
    setup.download.chunks = lambda: upstream

    def tracked(chunks, lost):
        wrapper = original(chunks, lost)
        wrappers.append(wrapper)
        return wrapper

    monkeypatch.setattr(service, "lease_checked_chunks", tracked)
    before = asyncio.all_tasks()
    try:
        assert await deliver(setup) == "deferred"
        assert closed.is_set()
        assert asyncio.all_tasks() == before
        setup.download.close.assert_awaited_once()
        setup.storage.upload_file_stream.assert_not_awaited()
        setup.repository.add_file_metadata.assert_not_awaited()
        service.document_publications.delivered.assert_not_awaited()
        service.document_publications.defer.assert_awaited_once()
        assert "private-source-marker" not in caplog.text
    finally:
        for wrapper in wrappers:
            await wrapper.aclose()
        await upstream.aclose()
