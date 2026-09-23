# ruff: noqa: E501 - SQL fragments mirror the persisted schema and stay searchable.
"""PostgreSQL source of truth for the autonomous workflow catalog.

The catalog's exact requests stay in ``workflow_catalog_examples`` for 90 days.
Qdrant receives a transient embedding input and a payload of safe, non-user fields only;
an outbox makes that projection recoverable and never blocks a chat run.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

_RETENTION = timedelta(days=90)
_MIN_SUCCESSES = 3


def chain_fingerprint(steps: list[str], cost_class: str) -> str:
    """Only an identical ordered chain and calculated cost class share a workflow."""
    canonical = json.dumps(
        {"steps": [str(step) for step in steps], "cost_class": str(cost_class)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def observe(
    session: Any,
    *,
    steps: list[str],
    cost_class: str,
    request_text: str,
    user_id: str | None,
    thread_id: str,
) -> None:
    """Store a successful normalized chain and materialize it after its third success."""
    if len(steps) < 2 or not request_text.strip():
        return
    fingerprint = chain_fingerprint(steps, cost_class)
    example_id = uuid.uuid4()
    now = _now()
    existing = (
        await session.execute(
            text("SELECT id FROM profile.workflow_catalog WHERE fingerprint = :fingerprint"),
            {"fingerprint": fingerprint},
        )
    ).scalar_one_or_none()
    await session.execute(
        text(
            "INSERT INTO profile.workflow_catalog_examples "
            "(id, fingerprint, workflow_id, steps, cost_class, user_id, thread_id, request_text, "
            "succeeded, created_at, expires_at) "
            "VALUES (:id, :fingerprint, :workflow_id, CAST(:steps AS jsonb), :cost_class, :user_id, "
            ":thread_id, :request_text, true, :created_at, :expires_at)"
        ),
        {
            "id": example_id,
            "fingerprint": fingerprint,
            "workflow_id": existing,
            "steps": json.dumps(steps, ensure_ascii=False),
            "cost_class": cost_class,
            "user_id": str(user_id) if user_id else None,
            "thread_id": str(thread_id),
            "request_text": request_text,
            "created_at": now,
            "expires_at": now + _RETENTION,
        },
    )
    if existing is None:
        successes = (
            await session.execute(
                text(
                    "SELECT count(*) FROM profile.workflow_catalog_examples "
                    "WHERE fingerprint = :fingerprint AND succeeded = true"
                ),
                {"fingerprint": fingerprint},
            )
        ).scalar_one()
        if int(successes or 0) < _MIN_SUCCESSES:
            return
        workflow_id = uuid.uuid4()
        point_id = uuid.uuid4()
        name = f"workflow_{fingerprint[:12]}"
        label = "Сохранённый сценарий"
        await session.execute(
            text(
                "INSERT INTO profile.workflow_catalog "
                "(id, fingerprint, name, label_ru, steps, cost_class, version, state, quality_score, "
                "reuse_score, index_point_id, created_at, updated_at) "
                "VALUES (:id, :fingerprint, :name, :label_ru, CAST(:steps AS jsonb), :cost_class, 1, "
                "'active', 0.8, 0.0, :point_id, :now, :now)"
            ),
            {
                "id": workflow_id,
                "fingerprint": fingerprint,
                "name": name,
                "label_ru": label,
                "steps": json.dumps(steps, ensure_ascii=False),
                "cost_class": cost_class,
                "point_id": point_id,
                "now": now,
            },
        )
        await session.execute(
            text(
                "UPDATE profile.workflow_catalog_examples SET workflow_id = :workflow_id "
                "WHERE fingerprint = :fingerprint AND workflow_id IS NULL"
            ),
            {"workflow_id": workflow_id, "fingerprint": fingerprint},
        )
        existing = workflow_id
    await _enqueue(session, workflow_id=existing, example_id=example_id, action="upsert")


async def record_execution(
    session: Any,
    *,
    workflow_id: str,
    version: int,
    thread_id: str,
    user_id: str | None,
    content_key: str,
    succeeded: bool,
) -> None:
    """Persist one selected catalog run idempotently by workflow/thread/content key."""
    if not workflow_id or not content_key:
        return
    await session.execute(
        text(
            "INSERT INTO profile.workflow_catalog_executions "
            "(id, workflow_id, workflow_version, user_id, thread_id, content_key, succeeded) "
            "VALUES (:id, CAST(:workflow_id AS uuid), :version, :user_id, :thread_id, :content_key, "
            ":succeeded) "
            "ON CONFLICT (workflow_id, thread_id, content_key) DO UPDATE "
            "SET succeeded = EXCLUDED.succeeded"
        ),
        {
            "id": uuid.uuid4(),
            "workflow_id": workflow_id,
            "version": int(version),
            "user_id": str(user_id) if user_id else None,
            "thread_id": str(thread_id),
            "content_key": content_key,
            "succeeded": bool(succeeded),
        },
    )


async def apply_feedback(
    session: Any,
    *,
    thread_id: str,
    content_key: str,
    user_id: str | None,
    rating: str,
) -> bool:
    """Upsert 👍/👎 against the catalog execution owning this assistant response."""
    if rating not in {"like", "dislike"}:
        return False
    execution_id = (
        await session.execute(
            text(
                "SELECT id FROM profile.workflow_catalog_executions "
                "WHERE thread_id = :thread_id AND content_key = :content_key "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"thread_id": str(thread_id), "content_key": content_key},
        )
    ).scalar_one_or_none()
    if execution_id is None:
        return False
    await session.execute(
        text(
            "INSERT INTO profile.workflow_catalog_feedback "
            "(id, execution_id, user_id, rating, created_at, updated_at) "
            "VALUES (:id, :execution_id, :user_id, :rating, now(), now()) "
            "ON CONFLICT (execution_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, "
            "updated_at = now()"
        ),
        {
            "id": uuid.uuid4(),
            "execution_id": execution_id,
            "user_id": str(user_id) if user_id else None,
            "rating": rating,
        },
    )
    return True


async def _enqueue(session: Any, *, workflow_id: Any, example_id: Any, action: str) -> None:
    await session.execute(
        text(
            "INSERT INTO profile.workflow_catalog_outbox "
            "(id, workflow_id, example_id, action, attempts, available_at, created_at) "
            "VALUES (:id, :workflow_id, :example_id, :action, 0, now(), now())"
        ),
        {
            "id": uuid.uuid4(),
            "workflow_id": workflow_id,
            "example_id": example_id,
            "action": action,
        },
    )


async def maintain(session: Any) -> dict[str, int]:
    """Expire examples and recompute scores/lifecycle without blocking chat execution."""
    expired = await session.execute(
        text("DELETE FROM profile.workflow_catalog_examples WHERE expires_at < now()")
    )
    await session.execute(
        text(
            "WITH stats AS ("
            " SELECT c.id, "
            "  (SELECT count(*) FROM profile.workflow_catalog_examples e WHERE e.workflow_id = c.id "
            "     AND e.succeeded) + "
            "  (SELECT count(*) FROM profile.workflow_catalog_executions x WHERE x.workflow_id = c.id "
            "     AND x.succeeded) AS successes, "
            "  (SELECT count(*) FROM profile.workflow_catalog_examples e WHERE e.workflow_id = c.id) + "
            "  (SELECT count(*) FROM profile.workflow_catalog_executions x WHERE x.workflow_id = c.id) AS runs, "
            "  (SELECT count(*) FROM profile.workflow_catalog_executions x WHERE x.workflow_id = c.id) AS executions, "
            "  (SELECT count(*) FROM profile.workflow_catalog_feedback f JOIN "
            "     profile.workflow_catalog_executions x ON x.id = f.execution_id "
            "     WHERE x.workflow_id = c.id AND f.rating = 'like') AS likes, "
            "  (SELECT count(*) FROM profile.workflow_catalog_feedback f JOIN "
            "     profile.workflow_catalog_executions x ON x.id = f.execution_id "
            "     WHERE x.workflow_id = c.id AND f.rating = 'dislike') AS dislikes, "
            "  (SELECT count(DISTINCT u.user_id) FROM ("
            "     SELECT e.user_id FROM profile.workflow_catalog_examples e WHERE e.workflow_id = c.id "
            "     UNION SELECT x.user_id FROM profile.workflow_catalog_executions x WHERE x.workflow_id = c.id"
            "   ) u WHERE u.user_id IS NOT NULL) AS users "
            " FROM profile.workflow_catalog c"
            ") "
            "UPDATE profile.workflow_catalog c SET "
            "quality_score = (stats.successes + stats.likes + 1.0) / "
            "  GREATEST(stats.runs + stats.likes + stats.dislikes + 2.0, 1.0), "
            "reuse_score = LEAST(stats.users / 5.0, 1.0), "
            "state = CASE "
            " WHEN stats.dislikes >= 3 AND "
            "   ((stats.successes + stats.likes + 1.0) / "
            "    GREATEST(stats.runs + stats.likes + stats.dislikes + 2.0, 1.0)) <= 0.25 THEN 'pruned' "
            " WHEN stats.executions >= 20 AND stats.users >= 5 AND (stats.likes + stats.dislikes) >= 5 AND "
            "   ((stats.successes + stats.likes + 1.0) / "
            "    GREATEST(stats.runs + stats.likes + stats.dislikes + 2.0, 1.0)) >= 0.75 THEN 'pinned' "
            " ELSE 'active' END, updated_at = now() "
            "FROM stats WHERE c.id = stats.id"
        )
    )
    # Scores and lifecycle state are part of the Qdrant payload. Enqueue a fresh safe
    # projection after every consolidation; a failed projection remains retriable here.
    rows = (
        await session.execute(
            text(
                "SELECT c.id, c.state, (SELECT e.id FROM profile.workflow_catalog_examples e "
                "WHERE e.workflow_id = c.id ORDER BY e.created_at DESC LIMIT 1) AS example_id "
                "FROM profile.workflow_catalog c"
            )
        )
    ).mappings()
    enqueued = 0
    for row in rows:
        await _enqueue(
            session,
            workflow_id=row["id"],
            example_id=row["example_id"],
            action="delete" if row["state"] == "pruned" else "upsert",
        )
        enqueued += 1
    return {"expired_examples": int(expired.rowcount or 0), "outbox_enqueued": enqueued}


async def pending_outbox(session: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    """Compatibility reader for diagnostics.

    Workers must use :func:`claim_pending_outbox`; this helper deliberately does
    not acquire leases and is kept only for read-only operational code.
    """
    rows = (
        await session.execute(
            text(
                "SELECT o.id, o.action, o.workflow_id, c.index_point_id, c.version, c.name, c.label_ru, "
                "c.steps, c.cost_class, c.state, c.quality_score, c.reuse_score, e.request_text "
                "FROM profile.workflow_catalog_outbox o "
                "JOIN profile.workflow_catalog c ON c.id = o.workflow_id "
                "LEFT JOIN profile.workflow_catalog_examples e ON e.id = o.example_id "
                "WHERE o.delivered_at IS NULL AND o.available_at <= now() "
                "ORDER BY o.created_at LIMIT :limit"
            ),
            {"limit": min(max(int(limit), 1), 100)},
        )
    ).mappings()
    return [dict(row) for row in rows]


async def claim_pending_outbox(
    session: Any,
    *,
    lease_sec: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Lease due outbox rows exactly once across concurrent maintenance workers.

    PostgreSQL row locks are held only while the claim transaction executes.
    Projection itself runs outside that transaction; a lease token makes a late
    worker unable to acknowledge a row claimed by a newer worker.
    """
    lease_token = uuid.uuid4()
    rows = (
        await session.execute(
            text(
                "WITH due AS ("
                " SELECT id FROM profile.workflow_catalog_outbox "
                " WHERE delivered_at IS NULL AND available_at <= now() "
                "   AND (lease_until IS NULL OR lease_until <= now()) "
                " ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT :limit"
                "), claimed AS ("
                " UPDATE profile.workflow_catalog_outbox o SET leased_at = now(), "
                " lease_until = now() + make_interval(secs => :lease_sec), "
                " lease_token = CAST(:lease_token AS uuid) "
                " FROM due WHERE o.id = due.id "
                " RETURNING o.id, o.action, o.workflow_id, o.lease_token"
                ") "
                "SELECT claimed.id, claimed.action, claimed.workflow_id, claimed.lease_token, "
                "c.index_point_id, c.version, c.name, c.label_ru, c.steps, c.cost_class, c.state, "
                "c.quality_score, c.reuse_score, e.request_text "
                "FROM claimed JOIN profile.workflow_catalog c ON c.id = claimed.workflow_id "
                "LEFT JOIN profile.workflow_catalog_examples e ON e.id = ("
                " SELECT example_id FROM profile.workflow_catalog_outbox WHERE id = claimed.id)"
            ),
            {
                "lease_sec": min(max(int(lease_sec), 10), 3600),
                "lease_token": str(lease_token),
                "limit": min(max(int(limit), 1), 100),
            },
        )
    ).mappings()
    return [dict(row) for row in rows]


async def mark_outbox(
    session: Any,
    *,
    outbox_id: Any,
    lease_token: Any,
    delivered: bool,
    error_class: str = "unknown",
    retry_max_sec: int = 3600,
) -> None:
    """Acknowledge a leased projection or release it with bounded backoff."""
    if delivered:
        await session.execute(
            text(
                "UPDATE profile.workflow_catalog_outbox SET delivered_at = now(), last_error = NULL, "
                "last_error_class = NULL, leased_at = NULL, lease_until = NULL, lease_token = NULL "
                "WHERE id = :id AND lease_token = CAST(:lease_token AS uuid)"
            ),
            {"id": outbox_id, "lease_token": str(lease_token)},
        )
        return
    await session.execute(
        text(
            "UPDATE profile.workflow_catalog_outbox SET attempts = attempts + 1, "
            "last_error = NULL, last_error_class = :error_class, leased_at = NULL, lease_until = NULL, "
            "lease_token = NULL, available_at = now() + make_interval(secs => LEAST(:retry_max_sec, "
            "5 * power(2, LEAST(attempts, 10)))) "
            "WHERE id = :id AND lease_token = CAST(:lease_token AS uuid)"
        ),
        {
            "id": outbox_id,
            "lease_token": str(lease_token),
            "error_class": _safe_error_class(error_class),
            "retry_max_sec": min(max(int(retry_max_sec), 10), 86400),
        },
    )


async def outbox_snapshot(session: Any) -> dict[str, int]:
    """Return aggregate queue health; exact request text is never selected."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT count(*) FILTER (WHERE delivered_at IS NULL) AS depth, "
                    "COALESCE(EXTRACT(EPOCH FROM now() - min(created_at) "
                    " FILTER (WHERE delivered_at IS NULL)), 0) AS oldest_age_sec "
                    "FROM profile.workflow_catalog_outbox"
                )
            )
        )
        .mappings()
        .one()
    )
    return {"depth": int(row["depth"] or 0), "oldest_age_sec": int(row["oldest_age_sec"] or 0)}


def _safe_error_class(value: str) -> str:
    allowed = {"transport", "timeout", "protocol", "remote", "unknown"}
    return value if value in allowed else "unknown"
