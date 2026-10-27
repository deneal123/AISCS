"""Durable outbox for audited Document Forge artifacts."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

PENDING_STATES = frozenset({"pending_audit", "pending_delivery"})
TERMINAL_CODES = frozenset({"workspace_expired", "artifact_mismatch", "artifact_invalid"})
ALLOWED_ROLES = frozenset({"pdf", "source_bundle"})
ALLOWED_MIME = frozenset({"application/pdf", "application/zip"})
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PublicationArtifactMismatch(ValueError):
    def __init__(self):
        super().__init__("artifact_mismatch")


def upload_intent(row: dict) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"gpthub-document:{row['user_id']}:{row['build_id']}:{row['artifact_id']}:{row['role']}",
    )


async def saved_file_id(session, row: dict) -> uuid.UUID | None:
    """Recover a committed owned artifact without trusting an unaudited intent alone."""
    result = await session.execute(
        text(
            """
            SELECT f.id, f.mode, f.original_name, f.content_sha256,
                   (j.status IN ('pending_delivery','delivered') OR COALESCE((
                       SELECT a.state='settled' AND a.failure_code IS NULL
                              AND a.charge_id IS NOT NULL
                       FROM profile.document_audit_attempt a
                       WHERE a.publication_job_id=j.id AND a.user_id=j.user_id
                         AND a.build_id=j.build_id AND a.source_digest=j.source_digest
                         AND a.artifact_sha256=j.artifact_sha256
                       ORDER BY a.created_at DESC, a.id DESC LIMIT 1
                   ), false)) AS audit_passed
            FROM profile.document_publication_job j
            JOIN profile.user_file f ON f.user_id=j.user_id AND f.upload_intent_id=:intent
            WHERE j.id=:id AND j.user_id=:user_id
              AND j.status IN ('pending_audit','pending_delivery','delivered')
            """
        ),
        {"id": row["id"], "user_id": row["user_id"], "intent": upload_intent(row)},
    )
    candidate = result.mappings().first()
    if candidate is None:
        return None
    if (
        candidate["mode"] != "CHAT"
        or candidate["original_name"] != (str(row["filename"]).strip() or None)
        or candidate["content_sha256"] != str(row["artifact_sha256"])
    ):
        raise PublicationArtifactMismatch()
    if not candidate["audit_passed"]:
        return None
    return candidate["id"]


async def delivery_completed(session, *, row: dict, file_id: uuid.UUID) -> bool:
    """Distinguish a completed replay from loss of a still-pending lease."""
    result = await session.execute(
        text(
            """
            SELECT id FROM profile.document_publication_job
            WHERE id=:id AND user_id=:user_id AND status='delivered'
              AND user_file_id=:file_id
            """
        ),
        {"id": row["id"], "user_id": row["user_id"], "file_id": file_id},
    )
    return result.scalar_one_or_none() is not None


def normalize_descriptors(raw: object) -> tuple[dict[str, Any], ...]:
    """Accept only bounded safe artifact facts emitted by an audited agents run."""

    result: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        mime = str(item.get("mime_type") or "")
        digest = str(item.get("sha256") or "").lower()
        source_digest = str(item.get("source_digest") or "").lower()
        filename = str(item.get("filename") or "").replace("\\", "/").rsplit("/", 1)[-1]
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
        if (
            role not in ALLOWED_ROLES
            or mime not in ALLOWED_MIME
            or not _DIGEST.fullmatch(digest)
            or not _DIGEST.fullmatch(source_digest)
            or not 0 < size <= 64 * 1024 * 1024
            or not filename
        ):
            continue
        build_id = str(item.get("build_id") or "")[:128]
        artifact_id = str(item.get("artifact_id") or "")[:128]
        if not build_id or not artifact_id:
            continue
        result.append(
            {
                "build_id": build_id,
                "artifact_id": artifact_id,
                "role": role,
                "source_digest": source_digest,
                "artifact_sha256": digest,
                "artifact_size": size,
                "filename": filename[:1000],
                "mime_type": mime,
                "initial_status": (
                    "pending_audit"
                    if item.get("initial_status") == "pending_audit"
                    else "pending_delivery"
                ),
            }
        )
    return tuple(result[:4])


async def enqueue(
    session,
    *,
    user_id: uuid.UUID,
    thread_id: str,
    workspace_id: str,
    billing_job_id: str,
    descriptors: tuple[dict[str, Any], ...],
    attach_to_latest: bool = True,
    initial_status: str = "pending_delivery",
    origin_message_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    status = initial_status if initial_status in PENDING_STATES else "pending_delivery"
    assistant_message_id = None
    origin = None
    if origin_message_id is not None:
        try:
            origin = uuid.UUID(str(origin_message_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("publication_message_invalid") from None
    if origin is not None or attach_to_latest:
        # Explicit job origin never falls back to a competing/latest reply.
        selection = (
            "AND m.message_id=:origin_message_id"
            if origin is not None
            else "ORDER BY m.id DESC LIMIT 1"
        )
        message_result = await session.execute(
            text(
                """
                SELECT m.id FROM profile.chat_messages m
                JOIN profile.chat_threads t ON t.id = m.thread_id
                WHERE t.thread_id=:thread_id AND t.user_id=:user_id
                  AND m.sender IN ('assistant', 'agent')
                """
                + selection
            ),
            {
                "thread_id": str(thread_id),
                "user_id": user_id,
                **({"origin_message_id": origin} if origin is not None else {}),
            },
        )
        assistant_message_id = message_result.scalar_one_or_none()
        if origin is not None and assistant_message_id is None:
            raise ValueError("publication_message_missing")
    rows: list[dict[str, Any]] = []
    # Replaying an accepted publication must not rewind an audit/delivery stage,
    # reset its retry backoff, or invalidate the worker's lease. State transitions
    # belong to the claim/audit/delivery repository operations, not enqueue.
    for descriptor in descriptors:
        row_status = (
            str(descriptor.get("initial_status"))
            if descriptor.get("initial_status") in PENDING_STATES
            else status
        )
        params = {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "thread_id": str(thread_id)[:128],
            "workspace_id": str(workspace_id)[:128],
            "billing_job_id": str(billing_job_id)[:128],
            "assistant_message_id": assistant_message_id,
            "initial_status": row_status,
            **{key: value for key, value in descriptor.items() if key != "initial_status"},
        }
        result = await session.execute(
            text(
                """
                INSERT INTO profile.document_publication_job
                    (id, user_id, thread_id, workspace_id, build_id, artifact_id, role,
                     source_digest, artifact_sha256, artifact_size, filename, mime_type,
                     status, attempts, next_attempt_at, billing_job_id, assistant_message_id,
                     created_at, updated_at)
                VALUES
                    (:id, :user_id, :thread_id, :workspace_id, :build_id, :artifact_id, :role,
                     :source_digest, :artifact_sha256, :artifact_size, :filename, :mime_type,
                     :initial_status, 0, now(), :billing_job_id, :assistant_message_id,
                     now(), now())
                ON CONFLICT (user_id, build_id, artifact_id, role)
                DO UPDATE SET
                    billing_job_id = COALESCE(
                        profile.document_publication_job.billing_job_id,
                        EXCLUDED.billing_job_id
                    ),
                    updated_at = profile.document_publication_job.updated_at
                RETURNING id, status, user_file_id
                """
            ),
            params,
        )
        row = result.mappings().first()
        if row:
            rows.append(dict(row))
    return tuple(rows)


async def claim(session, *, limit: int = 8, lease_sec: int = 120) -> tuple[dict, ...]:
    lease_token = uuid.uuid4()
    result = await session.execute(
        text(
            """
            WITH claimed AS (
                SELECT id FROM profile.document_publication_job
                WHERE status IN ('pending_audit', 'pending_delivery')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT :limit
            )
            UPDATE profile.document_publication_job j
            SET lease_token = :lease_token,
                lease_expires_at = now() + (:lease_sec * interval '1 second'),
                updated_at = now()
            FROM claimed WHERE j.id = claimed.id
            RETURNING j.*
            """
        ),
        {"limit": max(1, min(int(limit), 32)), "lease_token": lease_token, "lease_sec": lease_sec},
    )
    return tuple(dict(row) for row in result.mappings().all())


async def delivered(
    session, *, job_id: uuid.UUID, lease_token: uuid.UUID | None, file_id: uuid.UUID
) -> bool:
    if lease_token is None:
        return False
    result = await session.execute(
        text(
            """
            UPDATE profile.document_publication_job
            SET status='delivered', user_file_id=:file_id, failure_code=NULL,
                lease_token=NULL, lease_expires_at=NULL, updated_at=now()
            WHERE id=:id AND lease_token=:lease_token
              AND status IN ('pending_audit','pending_delivery')
              AND lease_expires_at > clock_timestamp()
            """
        ),
        {"id": job_id, "lease_token": lease_token, "file_id": file_id},
    )
    return bool(result.rowcount)


async def renew(
    session,
    *,
    job_id: uuid.UUID,
    lease_token: uuid.UUID,
    lease_sec: int = 120,
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE profile.document_publication_job
            SET lease_expires_at=clock_timestamp() + (:lease_sec * interval '1 second'),
                updated_at=now()
            WHERE id=:id AND lease_token=:lease_token
              AND status IN ('pending_audit','pending_delivery')
              AND lease_expires_at > clock_timestamp()
            """
        ),
        {
            "id": job_id,
            "lease_token": lease_token,
            "lease_sec": max(30, min(int(lease_sec), 600)),
        },
    )
    return bool(result.rowcount)


async def defer(
    session,
    *,
    job_id: uuid.UUID,
    lease_token: uuid.UUID | None,
    failure_code: str,
    terminal: bool = False,
) -> bool:
    if lease_token is None:
        return False
    code = failure_code if failure_code in TERMINAL_CODES else "unavailable"
    attempts_result = await session.execute(
        text("SELECT attempts, status FROM profile.document_publication_job WHERE id=:id"),
        {"id": job_id},
    )
    current = attempts_result.first()
    attempts = int((current[0] if current else 0) or 0) + 1
    current_status = str(current[1] if current else "pending_delivery")
    delay = min(3600, 30 * (2 ** min(attempts - 1, 7)))
    result = await session.execute(
        text(
            """
            UPDATE profile.document_publication_job
            SET status=:status, attempts=:attempts, failure_code=:failure_code,
                next_attempt_at=:next_attempt_at, lease_token=NULL,
                lease_expires_at=NULL, updated_at=now()
            WHERE id=:id AND lease_token=:lease_token
              AND status IN ('pending_audit','pending_delivery')
              AND lease_expires_at > clock_timestamp()
            """
        ),
        {
            "id": job_id,
            "lease_token": lease_token,
            "status": (
                "terminal"
                if terminal
                else "pending_audit"
                if current_status == "pending_audit"
                else "pending_delivery"
            ),
            "attempts": attempts,
            "failure_code": code,
            "next_attempt_at": datetime.now(UTC) + timedelta(seconds=delay),
        },
    )
    return bool(result.rowcount)


async def state_for_build(session, *, user_id: uuid.UUID, build_id: str) -> str | None:
    result = await session.execute(
        text(
            """
            SELECT status FROM profile.document_publication_job
            WHERE user_id=:user_id AND build_id=:build_id
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"user_id": user_id, "build_id": build_id},
    )
    value = result.scalar_one_or_none()
    return str(value) if value else None


async def snapshot(session) -> dict[str, int]:
    result = await session.execute(
        text(
            """
            SELECT count(*) FILTER (WHERE status IN ('pending_audit','pending_delivery')) AS depth,
                   COALESCE(EXTRACT(EPOCH FROM now() - min(created_at)) FILTER
                     (WHERE status IN ('pending_audit','pending_delivery')), 0)::int AS oldest_age
            FROM profile.document_publication_job
            """
        )
    )
    row = result.mappings().one()
    return {"depth": int(row["depth"] or 0), "oldest_age": int(row["oldest_age"] or 0)}


__all__ = [
    "claim",
    "defer",
    "delivered",
    "enqueue",
    "normalize_descriptors",
    "renew",
    "snapshot",
    "state_for_build",
]
