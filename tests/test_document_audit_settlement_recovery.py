"""Crash recovery must settle accepted usage before consulting artifact readiness."""

import uuid
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"state": "ready"}, "ready"),
        ({"state": "failed"}, "artifact_invalid"),
        ({"state": "cancelled"}, "artifact_invalid"),
        (None, "workspace_expired"),
    ],
)
async def test_completed_or_missing_build_settles_saved_usage(monkeypatch, status, expected):
    attempt_id = uuid.uuid4()
    usage = {"total": 33, "calls": [{"model": "vision", "prompt": 30, "completion": 3}]}
    pending = AsyncMock(return_value={"id": attempt_id, "usage_envelope": usage})
    charge = AsyncMock(return_value="charge-1")
    settle = AsyncMock(return_value=True)
    audit = AsyncMock()
    session = AsyncMock()
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    monkeypatch.setattr(service.document_audit_attempts, "pending_charge", pending)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service, "audit_document", audit)
    row = {
        "id": uuid.uuid4(),
        "build_id": "opaque-build",
        "source_digest": "a" * 64,
        "artifact_id": "opaque-artifact",
        "artifact_sha256": "b" * 64,
        "artifact_size": 4,
        "mime_type": "application/pdf",
    }
    if status is not None:
        status.update(
            build_id=row["build_id"],
            source_digest=row["source_digest"],
            artifacts=[
                {
                    "artifact_id": row["artifact_id"],
                    "sha256": row["artifact_sha256"],
                    "size": 4,
                    "mime_type": "application/pdf",
                }
            ],
        )
    monkeypatch.setattr(
        service.document_audit_attempts, "confirm_attestation", AsyncMock(return_value=False)
    )
    result = await service._ensure_audited_durable(
        config=object(), pg_connector=object(), redis=object(), session=session, ref={}, row=row
    )
    assert result == expected
    assert charge.await_args.kwargs["usage"] == usage
    assert charge.await_args.kwargs["attempt_id"] == attempt_id
    settle.assert_awaited_once_with(session, attempt_id=attempt_id, charge_id="charge-1")
    session.commit.assert_awaited_once()
    audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_charge_does_not_settle_or_release_artifact(monkeypatch):
    session = AsyncMock()
    settle = AsyncMock()
    monkeypatch.setattr(
        service, "document_build_status", AsyncMock(return_value={"state": "ready"})
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "pending_charge",
        AsyncMock(return_value={"id": uuid.uuid4(), "usage_envelope": {"total": 1, "calls": [{}]}}),
    )
    monkeypatch.setattr(
        service, "_charge_visual_audit", AsyncMock(side_effect=RuntimeError("charge"))
    )
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    with pytest.raises(RuntimeError):
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=session,
            ref={},
            row={"id": uuid.uuid4(), "build_id": "opaque-build"},
        )
    settle.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [service.WorkspaceGone, service.WorkspaceUnavailable])
async def test_status_exception_is_raised_only_after_usage_settlement(monkeypatch, failure_type):
    session = AsyncMock()
    attempt_id = uuid.uuid4()
    charge = AsyncMock(return_value="same-charge")
    settle = AsyncMock(return_value=True)
    monkeypatch.setattr(
        service.document_audit_attempts,
        "pending_charge",
        AsyncMock(return_value={"id": attempt_id, "usage_envelope": {"total": 1, "calls": [{}]}}),
    )
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service, "document_build_status", AsyncMock(side_effect=failure_type()))
    with pytest.raises(failure_type):
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=session,
            ref={},
            row={"id": uuid.uuid4(), "build_id": "opaque-build"},
        )
    settle.assert_awaited_once_with(session, attempt_id=attempt_id, charge_id="same-charge")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_binding_settles_before_terminal_and_redelivery_does_not_charge(monkeypatch):
    monkeypatch.setattr(
        service.document_publications, "saved_file_id", AsyncMock(return_value=None)
    )
    attempt_id = uuid.uuid4()
    pending = AsyncMock(
        side_effect=[{"id": attempt_id, "usage_envelope": {"total": 1, "calls": [{}]}}, None]
    )
    charge = AsyncMock(return_value="charge-once")
    settle = AsyncMock(return_value=True)
    defer = AsyncMock(return_value=True)
    monkeypatch.setattr(service.document_audit_attempts, "pending_charge", pending)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service, "read_binding", AsyncMock(return_value=None))
    monkeypatch.setattr(service.document_publications, "defer", defer)
    row = {"id": uuid.uuid4(), "lease_token": uuid.uuid4(), "thread_id": "thread"}
    session = AsyncMock()
    for _ in range(2):
        assert (
            await service.deliver_one(
                config=object(),
                pg_connector=object(),
                redis=object(),
                file_service=object(),
                session=session,
                row=row,
            )
            == "terminal"
        )
    charge.assert_awaited_once()
    settle.assert_awaited_once()
    session.commit.assert_awaited_once()
    assert defer.await_count == 2
