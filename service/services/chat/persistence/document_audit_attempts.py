"""Persistence seam for idempotently settled visual-audit calls."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text

_FAILURES = frozenset(
    {"", "audit_failed", "audit_unavailable", "provider_protocol", "timeout", "internal"}
)


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
        return dict(current)
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
        return dict(value)
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
        return dict(current)
    raise RuntimeError("document_audit_attempt_conflict")


async def record_result(
    session: Any,
    *,
    attempt_id: uuid.UUID,
    usage: dict[str, Any],
    failure_code: str = "",
) -> bool:
    code = failure_code if failure_code in _FAILURES else "internal"
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
            "usage": json.dumps(usage, separators=(",", ":")),
            "failure_code": code or None,
        },
    )
    return bool(result.rowcount)


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
            WHERE id=:id AND state IN ('started','charge_pending')
            """
        ),
        {"id": attempt_id, "charge_id": str(charge_id)[:128]},
    )
    return bool(result.rowcount)


__all__ = ["begin", "record_result", "settle"]
