"""Audit usage is durable, but only the exact ready source/artifact is publication proof."""

import uuid
from unittest.mock import AsyncMock

import pytest

from service.services.chat.application.documents.publication import service as service
from tests.document_publication_fixtures import no_started_audit_rows as no_started_audit_rows


def facts():
    row = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "build_id": "opaque-build",
        "source_digest": "a" * 64,
        "artifact_id": "opaque-artifact",
        "artifact_sha256": "b" * 64,
        "artifact_size": 4,
        "mime_type": "application/pdf",
    }
    status = {
        "build_id": row["build_id"],
        "source_digest": row["source_digest"],
        "state": "ready",
        "artifacts": [
            {
                "artifact_id": row["artifact_id"],
                "sha256": row["artifact_sha256"],
                "size": row["artifact_size"],
                "mime_type": row["mime_type"],
            }
        ],
    }
    return row, status


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_usage", [{}, {"total": 33}])
@pytest.mark.parametrize("permission", [False, None, 1, "true"])
async def test_redelivery_cannot_restart_unresolved_paid_attempt(
    monkeypatch, saved_usage, permission
):
    row, status = facts()
    status["state"] = "visual_pending"
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    monkeypatch.setattr(service, "recover_started_result", AsyncMock(return_value=None))
    monkeypatch.setattr(
        service.document_audit_attempts, "attestation_pending", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "state": "started",
                "usage_envelope": saved_usage,
                "may_execute": permission,
            }
        ),
    )
    audit = AsyncMock(return_value={"passed": False, "retryable": True, "usage": {}})
    before = AsyncMock()
    charge = AsyncMock()
    settle = AsyncMock()
    recorded = AsyncMock(
        return_value=service.document_audit_attempts.RecordedAuditResult({}, "audit_unavailable")
    )
    monkeypatch.setattr(service, "audit_document", audit)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service.document_audit_attempts, "record_merged_result", recorded)
    assert (
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=AsyncMock(),
            ref={},
            row=row,
            before_audit=before,
        )
        == "unavailable"
    )
    audit.assert_not_awaited()
    before.assert_not_awaited()
    charge.assert_not_awaited()
    settle.assert_not_awaited()
    recorded.assert_not_awaited()


@pytest.mark.parametrize("field", ["build_id", "source_digest"])
def test_artifact_hash_alone_does_not_prove_the_requested_source(field):
    row, status = facts()
    status[field] = "c" * 64
    assert service._matching_artifact(status, row) is None


@pytest.mark.asyncio
async def test_sealed_recovery_uses_existing_settlement_without_new_model_call(monkeypatch):
    row, status = facts()
    status["state"] = "visual_pending"
    attempt = uuid.uuid4()
    usage = {"total": 33, "calls": [{"model": "GigaChat-2-Max", "prompt": 30, "completion": 3}]}
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    monkeypatch.setattr(
        service.document_audit_attempts, "attestation_pending", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(
            return_value={
                "id": attempt,
                "state": "started",
                "may_execute": False,
            }
        ),
    )
    recovered = service.document_audit_attempts.RecordedAuditResult(usage, "audit_unavailable")
    monkeypatch.setattr(service, "recover_started_result", AsyncMock(return_value=recovered))
    audit = AsyncMock()
    before = AsyncMock()
    charge = AsyncMock(return_value="existing-charge-key")
    settle = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "audit_document", audit)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    assert (
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=AsyncMock(),
            ref={},
            row=row,
            before_audit=before,
        )
        == "unavailable"
    )
    audit.assert_not_awaited()
    before.assert_not_awaited()
    charge.assert_awaited_once()
    assert charge.await_args.kwargs["usage"] == usage
    assert charge.await_args.kwargs["attempt_id"] == attempt
    settle.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["build_id", "source_digest"])
async def test_source_mismatch_never_starts_new_audit(monkeypatch, field):
    row, status = facts()
    status.update(state="visual_pending", **{field: "c" * 64})
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    audit, begin = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "audit_document", audit)
    monkeypatch.setattr(service.document_audit_attempts, "begin", begin)
    assert (
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=AsyncMock(),
            ref={},
            row=row,
        )
        == "artifact_mismatch"
    )
    audit.assert_not_awaited()
    begin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol_conflict", [False, True])
async def test_settlement_consumes_recorded_usage_not_remote_envelope(
    monkeypatch, protocol_conflict
):
    row, status = facts()
    status["state"] = "visual_pending"
    attempt_id = uuid.uuid4()
    saved = {"total": 33, "calls": [{"model": "GigaChat-2", "prompt": 30, "completion": 3}]}
    failure = "provider_protocol" if protocol_conflict else "audit_unavailable"
    recorded = service.document_audit_attempts.RecordedAuditResult(saved, failure)
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    build = AsyncMock(return_value=status)
    monkeypatch.setattr(service, "document_build_status", build)
    monkeypatch.setattr(
        service.document_audit_attempts, "attestation_pending", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(return_value={"id": attempt_id, "state": "started", "may_execute": True}),
    )
    monkeypatch.setattr(
        service,
        "audit_document",
        AsyncMock(
            return_value={
                "passed": protocol_conflict,
                "retryable": not protocol_conflict,
                "usage": {},
            }
        ),
    )
    monkeypatch.setattr(
        service.document_audit_attempts, "record_merged_result", AsyncMock(return_value=recorded)
    )
    charge = AsyncMock(return_value="accepted-charge")
    settle = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    result = await service._ensure_audited_durable(
        config=object(),
        pg_connector=object(),
        redis=object(),
        session=AsyncMock(),
        ref={},
        row=row,
    )
    assert result == ("artifact_invalid" if protocol_conflict else "unavailable")
    assert charge.await_args.kwargs["usage"] == saved
    assert charge.await_args.kwargs["attempt_id"] == attempt_id
    settle.assert_awaited_once()
    build.assert_awaited_once()  # A contradictory remote success never reaches attestation.


@pytest.mark.asyncio
@pytest.mark.parametrize("matching", [False, True])
async def test_accepted_usage_is_paid_but_success_requires_ready_attestation(monkeypatch, matching):
    row, ready = facts()
    pending = {**ready, "state": "visual_pending"}
    if not matching:
        ready["source_digest"] = "c" * 64
    usage = {"total": 3, "calls": [{"model": "vision", "prompt": 2, "completion": 1}]}
    attempt_id = uuid.uuid4()
    session = AsyncMock()
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(side_effect=[pending, ready]))
    monkeypatch.setattr(
        service, "audit_document", AsyncMock(return_value={"passed": True, "usage": usage})
    )
    monkeypatch.setattr(
        service.document_audit_attempts,
        "begin",
        AsyncMock(return_value={"id": attempt_id, "state": "started", "may_execute": True}),
    )
    record, charge, settle, confirm = (
        AsyncMock(
            return_value=service.document_audit_attempts.RecordedAuditResult(
                usage, "attestation_pending"
            )
        ),
        AsyncMock(return_value="one-charge"),
        AsyncMock(),
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(service.document_audit_attempts, "record_merged_result", record)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    # New repository checkpoints are mocked here; SQL proof is tested independently.
    monkeypatch.setattr(
        service.document_audit_attempts,
        "attestation_pending",
        AsyncMock(return_value=False),
        raising=False,
    )
    monkeypatch.setattr(
        service.document_audit_attempts, "confirm_attestation", confirm, raising=False
    )
    assert await service._ensure_audited_durable(
        config=object(),
        pg_connector=object(),
        redis=object(),
        session=session,
        ref={},
        row=row,
    ) == ("ready" if matching else "artifact_mismatch")
    record.assert_awaited_once_with(
        session, attempt_id=attempt_id, usage=usage, failure_code="attestation_pending"
    )
    charge.assert_awaited_once()
    settle.assert_awaited_once_with(session, attempt_id=attempt_id, charge_id="one-charge")
    if matching:
        confirm.assert_awaited_once_with(session, row)
    else:
        confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_attestation_does_not_repeat_a_paid_visual_call(monkeypatch):
    row, status = facts()
    status["state"] = "visual_pending"
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(service, "document_build_status", AsyncMock(return_value=status))
    monkeypatch.setattr(
        service.document_audit_attempts,
        "attestation_pending",
        AsyncMock(return_value=True),
        raising=False,
    )
    audit, begin = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "audit_document", audit)
    monkeypatch.setattr(service.document_audit_attempts, "begin", begin)
    assert (
        await service._ensure_audited_durable(
            config=object(),
            pg_connector=object(),
            redis=object(),
            session=AsyncMock(),
            ref={},
            row=row,
        )
        == "unavailable"
    )
    audit.assert_not_awaited()
    begin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("refresh", ["missing", "waiting", "mismatch"])
async def test_ready_recovery_confirms_paid_attempt_without_another_call(monkeypatch, refresh):
    row, ready = facts()
    pending = {**ready, "state": "visual_pending"}
    refreshed = {
        "missing": None,
        "waiting": pending,
        "mismatch": {**ready, "source_digest": "c" * 64},
    }[refresh]
    events = []
    attempt_id = uuid.uuid4()
    session = AsyncMock()
    monkeypatch.setattr(service, "_settle_pending_audit", AsyncMock())
    monkeypatch.setattr(
        service,
        "document_build_status",
        AsyncMock(side_effect=[pending, refreshed, pending, ready]),
    )
    audit = AsyncMock(return_value={"passed": True, "usage": {"total": 3}})
    monkeypatch.setattr(service, "audit_document", audit)
    begin = AsyncMock(return_value={"id": attempt_id, "state": "started", "may_execute": True})
    monkeypatch.setattr(service.document_audit_attempts, "begin", begin)
    monkeypatch.setattr(
        service.document_audit_attempts,
        "attestation_pending",
        AsyncMock(side_effect=[False, True]),
    )

    async def record(*args, **kwargs):
        events.append(("record", kwargs["failure_code"]))
        return service.document_audit_attempts.RecordedAuditResult(
            kwargs["usage"], kwargs["failure_code"]
        )

    async def charge(**kwargs):
        events.append(("charge", kwargs["attempt_id"]))
        return "one-charge"

    async def settle(*args, **kwargs):
        events.append(("settle", kwargs["charge_id"]))

    async def confirm(*args, **kwargs):
        events.append(("confirm", None))
        return True

    monkeypatch.setattr(service.document_audit_attempts, "record_merged_result", record)
    monkeypatch.setattr(service, "_charge_visual_audit", charge)
    monkeypatch.setattr(service.document_audit_attempts, "settle", settle)
    monkeypatch.setattr(service.document_audit_attempts, "confirm_attestation", confirm)
    params = dict(
        config=object(), pg_connector=object(), redis=object(), session=session, ref={}, row=row
    )
    first = "artifact_mismatch" if refresh == "mismatch" else "unavailable"
    assert await service._ensure_audited_durable(**params) == first
    assert events == [
        ("record", "attestation_pending"),
        ("charge", attempt_id),
        ("settle", "one-charge"),
    ]
    # A still-pending sidecar cannot trigger another metered call. When its
    # exact ready proof becomes available, reconcile only that proof.
    assert await service._ensure_audited_durable(**params) == "unavailable"
    assert await service._ensure_audited_durable(**params) == "ready"
    assert events[-1] == ("confirm", None)
    assert len(events) == 4
    audit.assert_awaited_once()
    begin.assert_awaited_once()
