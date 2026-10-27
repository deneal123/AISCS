"""Owned monotonic receipt persistence; caller commits before acknowledging it.

This stages expense only. It neither finalizes an audit nor performs charging.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from service.infrastructure.agents_client.document_audit.client import (
    _bounded_usage,
    _project_usage,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal

JOURNAL_KEY = "_audit_usage_journal"


class AuditCheckpointUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("document_audit_checkpoint_unavailable")


def merge_terminal_usage(stored: object, incoming: dict, *, attempt_id: UUID) -> tuple[dict, bool]:
    """Preserve persisted expense; contradictory receipts cannot certify an audit."""
    if stored is None:
        stored = {}
    if not isinstance(stored, dict):
        raise AuditCheckpointUnavailable()
    if JOURNAL_KEY not in stored:
        if not stored:
            return incoming, True  # Preserve the existing non-checkpoint projection.
        if not isinstance(stored.get("calls"), list):
            raise AuditCheckpointUnavailable()
        usage, consistent = _project_usage(
            {"calls": [*stored.get("calls", []), *incoming.get("calls", [])]}
        )
        return usage, consistent
    try:
        journal = UsageJournal.decode(stored[JOURNAL_KEY])
        if journal.attempt_id != str(attempt_id):
            raise ValueError
        if any(receipt.kind != "document_visual_audit" for receipt in journal.receipts):
            raise ValueError
        usage, consistent = _project_usage(
            {
                "calls": [
                    *[receipt.payload() for receipt in journal.receipts],
                    *incoming.get("calls", []),
                ]
            }
        )
        usage[JOURNAL_KEY] = journal.payload()
        return usage, consistent
    except Exception:
        raise AuditCheckpointUnavailable() from None


async def stage_checkpoint(session: Any, *, row: dict, payload: object) -> bool:
    """`row` must be the authenticated publication row, never caller-supplied scope."""
    try:
        journal = UsageJournal.decode(payload)
        if any(receipt.kind != "document_visual_audit" for receipt in journal.receipts):
            raise ValueError
        params = {
            "attempt": UUID(journal.attempt_id),
            "publication": row["id"],
            "owner": row["user_id"],
            "build": row["build_id"],
            "source": row["source_digest"],
            "artifact": row["artifact_sha256"],
        }
        result = await session.execute(
            text("""
                SELECT state, usage_envelope FROM profile.document_audit_attempt
                WHERE id=:attempt AND publication_job_id=:publication AND user_id=:owner
                  AND build_id=:build AND source_digest=:source AND artifact_sha256=:artifact
                FOR UPDATE
            """),
            params,
        )
        current = result.mappings().first()
        if current is None or current["state"] != "started":
            raise ValueError
        stored = current.get("usage_envelope")
        if stored is None:
            stored = {}
        if not isinstance(stored, dict):
            raise ValueError
        if JOURNAL_KEY in stored:
            previous = UsageJournal.decode(stored[JOURNAL_KEY])
            if journal == previous:
                return False
            if not journal.extends(previous):
                raise ValueError
        elif stored:
            # Legacy/noncanonical expense cannot be silently overwritten.
            raise ValueError
        usage = _bounded_usage({"calls": [receipt.payload() for receipt in journal.receipts]})
        usage[JOURNAL_KEY] = journal.payload()
        updated = await session.execute(
            text("""
                UPDATE profile.document_audit_attempt
                SET usage_envelope=CAST(:usage AS JSONB)
                WHERE id=:attempt AND publication_job_id=:publication AND user_id=:owner
                  AND build_id=:build AND source_digest=:source AND artifact_sha256=:artifact
                  AND state='started'
            """),
            {**params, "usage": json.dumps(usage, separators=(",", ":"))},
        )
        if updated.rowcount != 1:
            raise ValueError
        return True
    except Exception:
        raise AuditCheckpointUnavailable() from None
