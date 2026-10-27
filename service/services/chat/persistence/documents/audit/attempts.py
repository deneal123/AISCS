"""Persistence seam for idempotently settled visual-audit calls."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from service.services.chat.persistence.documents.audit.checkpoint import merge_terminal_usage


@dataclass(frozen=True, slots=True)
class RecordedAuditResult:
    usage: dict[str, Any]
    failure_code: str


_FAILURES = frozenset(
    {
        "",
        "audit_failed",
        "audit_unavailable",
        "attestation_pending",
        "provider_protocol",
        "timeout",
        "internal",
    }
)


def _attestation_params(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key] for key in ("id", "user_id", "build_id", "source_digest", "artifact_sha256")
    }


async def attestation_pending(session: Any, row: dict[str, Any]) -> bool:
    result = await session.execute(
        text(
            """
            SELECT id FROM profile.document_audit_attempt
            WHERE publication_job_id=:id AND user_id=:user_id AND build_id=:build_id
              AND source_digest=:source_digest AND artifact_sha256=:artifact_sha256
              AND state='settled' AND failure_code='attestation_pending'
              AND charge_id IS NOT NULL LIMIT 1
            """
        ),
        _attestation_params(row),
    )
    return result.scalar_one_or_none() is not None


async def confirm_attestation(session: Any, row: dict[str, Any]) -> bool:
    """Separate payable usage from proof of the exact published ready artifact."""
    result = await session.execute(
        text(
            """
            UPDATE profile.document_audit_attempt SET failure_code=NULL
            WHERE publication_job_id=:id AND user_id=:user_id AND build_id=:build_id
              AND source_digest=:source_digest AND artifact_sha256=:artifact_sha256
              AND state='settled' AND failure_code='attestation_pending'
              AND charge_id IS NOT NULL
            """
        ),
        _attestation_params(row),
    )
    return bool(result.rowcount)


async def pending_charge(session: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """Recover accepted usage even after the sidecar has completed its audit."""
    result = await session.execute(
        text(
            """
            SELECT id, state, usage_envelope, failure_code, charge_id
            FROM profile.document_audit_attempt
            WHERE publication_job_id=:publication_job_id AND state='charge_pending'
            ORDER BY created_at DESC LIMIT 1 FOR UPDATE
            """
        ),
        {"publication_job_id": row["id"]},
    )
    current = result.mappings().first()
    return dict(current) if current else None


async def lock_started(session: Any, row: dict[str, Any], *, attempt_id: uuid.UUID) -> bool:
    result = await session.execute(
        text("""
            SELECT id FROM profile.document_audit_attempt
            WHERE id=:attempt_id AND publication_job_id=:id AND user_id=:user_id
              AND build_id=:build_id AND source_digest=:source_digest
              AND artifact_sha256=:artifact_sha256 AND state='started'
            FOR UPDATE
        """),
        {**_attestation_params(row), "attempt_id": attempt_id},
    )
    return result.scalar_one_or_none() is not None


async def started_id(session: Any, row: dict[str, Any]) -> uuid.UUID | None:
    """Read from an already owned publication row; never create an attempt."""
    result = await session.execute(
        text("""
            SELECT id FROM profile.document_audit_attempt
            WHERE publication_job_id=:id AND state='started' LIMIT 1
        """),
        {"id": row["id"]},
    )
    value = result.scalar_one_or_none()
    return uuid.UUID(str(value)) if value is not None else None


async def begin(session: Any, row: dict[str, Any]) -> dict[str, Any]:
    existing = await session.execute(
        text(
            """
            SELECT id, state, usage_envelope, failure_code, charge_id
            FROM profile.document_audit_attempt
            WHERE publication_job_id=:publication_job_id AND state IN ('started','charge_pending')
            ORDER BY created_at DESC LIMIT 1
            FOR UPDATE
            """
        ),
        {"publication_job_id": row["id"]},
    )
    current = existing.mappings().first()
    if current:
        return {**dict(current), "may_execute": False}
    attempt_id = uuid.uuid4()
    result = await session.execute(
        text(
            """
            INSERT INTO profile.document_audit_attempt
                (id, publication_job_id, user_id, build_id, source_digest,
                 artifact_sha256, state, created_at)
            VALUES
                (:id, :publication_job_id, :user_id, :build_id, :source_digest,
                 :artifact_sha256, 'started', now())
            ON CONFLICT (publication_job_id)
                WHERE state IN ('started','charge_pending')
                DO NOTHING
            RETURNING id, state
            """
        ),
        {
            "id": attempt_id,
            "publication_job_id": row["id"],
            "user_id": row["user_id"],
            "build_id": str(row["build_id"]),
            "source_digest": str(row["source_digest"]),
            "artifact_sha256": str(row["artifact_sha256"]),
        },
    )
    value = result.mappings().first()
    if value:
        return {**dict(value), "may_execute": True}
    raced = await session.execute(
        text(
            """
            SELECT id, state, usage_envelope, failure_code, charge_id
            FROM profile.document_audit_attempt
            WHERE publication_job_id=:publication_job_id
              AND state IN ('started','charge_pending')
            ORDER BY created_at DESC LIMIT 1
            FOR UPDATE
            """
        ),
        {"publication_job_id": row["id"]},
    )
    current = raced.mappings().first()
    if current:
        return {**dict(current), "may_execute": False}
    raise RuntimeError("document_audit_attempt_conflict")


async def record_result(
    session: Any,
    *,
    attempt_id: uuid.UUID,
    usage: dict[str, Any],
    failure_code: str = "",
) -> bool:
    """Compatibility facade; production consumes the exact persisted envelope."""
    return (
        await record_merged_result(
            session, attempt_id=attempt_id, usage=usage, failure_code=failure_code
        )
        is not None
    )


async def record_merged_result(
    session: Any,
    *,
    attempt_id: uuid.UUID,
    usage: dict[str, Any],
    failure_code: str = "",
) -> RecordedAuditResult | None:
    locked = await session.execute(
        text("""
            SELECT state, usage_envelope FROM profile.document_audit_attempt
            WHERE id=:id FOR UPDATE
        """),
        {"id": attempt_id},
    )
    current = locked.mappings().first()
    if current is None or current["state"] != "started":
        return None
    merged, consistent = merge_terminal_usage(
        current.get("usage_envelope"), usage, attempt_id=attempt_id
    )
    code = failure_code if failure_code in _FAILURES else "internal"
    if not consistent:
        code = "provider_protocol"
    result = await session.execute(
        text(
            """
            UPDATE profile.document_audit_attempt
            SET state='charge_pending', usage_envelope=CAST(:usage AS JSONB),
                failure_code=:failure_code
            WHERE id=:id AND state='started'
            """
        ),
        {
            "id": attempt_id,
            "usage": json.dumps(merged, separators=(",", ":")),
            "failure_code": code or None,
        },
    )
    return RecordedAuditResult(merged, code) if result.rowcount == 1 else None


async def settle(
    session: Any,
    *,
    attempt_id: uuid.UUID,
    charge_id: str,
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE profile.document_audit_attempt
            SET state='settled', charge_id=:charge_id, settled_at=now()
            WHERE id=:id AND state='charge_pending'
            """
        ),
        {"id": attempt_id, "charge_id": str(charge_id)[:128]},
    )
    return bool(result.rowcount)


__all__ = ["begin", "pending_charge", "record_result", "settle"]
