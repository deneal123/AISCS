"""Recoverable Document Forge audit and Library delivery orchestration."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from functools import partial
from typing import Any

from sqlalchemy import text

from service.infrastructure.agents_client.document_audit.client import audit_document
from service.infrastructure.workspace_client import (
    DocumentArtifactMissing,
    WorkspaceGone,
    WorkspaceUnavailable,
    document_build_status,
    read_binding,
    stream_document_artifact,
)
from service.models.key_value import ServiceType
from service.services.chat.application.documents.audit.invocation import (
    audit_failure_code,
    invoke_fresh_audit,
)
from service.services.chat.application.documents.audit.reconciliation import reconcile_started_audit
from service.services.chat.application.documents.audit.recovery import recover_started_result
from service.services.chat.application.documents.publication.lease import (
    PublicationLeaseLost,
    lease_checked_chunks,
    require_publication_lease,
)
from service.services.chat.application.documents.publication.lease import (
    renewing_publication_lease as _renewing_publication_lease,
)
from service.services.chat.application.workspace_collaboration import mint_capability
from service.services.chat.persistence.documents import publication as document_publications
from service.services.chat.persistence.documents.audit import attempts as document_audit_attempts

logger = logging.getLogger(__name__)


def _agent_ref(binding: dict, row: dict) -> dict:
    expires_at = float(binding.get("expires_at") or 0)
    return {
        **binding,
        "user_id": str(row["user_id"]),
        "coordination_capability": mint_capability(
            str(binding["workspace_id"]),
            role="agent",
            actor_seed=f"publication:{row['id']}",
            expires_at=expires_at,
            run_id=str(row["billing_job_id"] or row["id"]),
        ),
    }


async def _charge_visual_audit(
    *,
    config: Any,
    pg_connector: Any,
    redis: Any,
    row: dict,
    usage: dict,
    attempt_id: uuid.UUID | None = None,
) -> str | None:
    """Charge one deferred audit through the existing idempotent billing seam."""

    calls = usage.get("calls") if isinstance(usage.get("calls"), list) else []
    total = max(0, int(usage.get("total") or 0))
    if total < 1 or not calls:
        return None
    from service.services.chat.infrastructure.chat_worker.billing.charging import _charge_usage

    model = str(usage.get("model") or (calls[0] if calls else {}).get("model") or "")
    charge_key = str(attempt_id) if attempt_id is not None else str(row["build_id"])
    result = await _charge_usage(
        pg_connector=pg_connector,
        redis_client=redis,
        user_id=str(row["user_id"]),
        execution_result={
            "prompt_tokens": max(0, int(usage.get("prompt") or 0)),
            "completion_tokens": max(0, int(usage.get("completion") or 0)),
            "total_tokens": total,
            "per_call_usage": calls,
            "reply_chars_count": 1,
        },
        thread_id=str(row["thread_id"]),
        job_id=f"{row['billing_job_id']}:document-audit:{charge_key}",
        resolved_model=model or None,
        selected_model=model or None,
        config=config,
        require_persisted=True,
    )
    return str(result) if result is not None else "settled"


async def _settle_pending_audit(
    *, config: Any, pg_connector: Any, redis: Any, session: Any, row: dict
) -> None:
    """Persisted usage is payable independently of temporary artifact availability."""
    pending = await document_audit_attempts.pending_charge(session, row)
    if pending is None:
        return
    attempt_id = uuid.UUID(str(pending["id"]))
    charge_id = await _charge_visual_audit(
        config=config,
        pg_connector=pg_connector,
        redis=redis,
        row=row,
        usage=pending.get("usage_envelope") or {},
        attempt_id=attempt_id,
    )
    await document_audit_attempts.settle(
        session, attempt_id=attempt_id, charge_id=charge_id or "no_usage"
    )
    await session.commit()


async def _ensure_audited_durable(
    *,
    config: Any,
    pg_connector: Any,
    redis: Any,
    session: Any,
    ref: dict,
    row: dict,
    before_audit: Callable[[], Awaitable[None]] | None = None,
) -> str:
    """Persist and settle every accepted deferred visual call before delivery decisions."""

    await _settle_pending_audit(
        config=config, pg_connector=pg_connector, redis=redis, session=session, row=row
    )
    if not await reconcile_started_audit(
        config,
        pg_connector,
        redis,
        session,
        row,
        _settle_pending_audit,
    ):
        return "unavailable"
    status = await document_build_status(ref, build_id=str(row["build_id"]))
    if not isinstance(status, dict):
        return "workspace_expired"
    if not _matching_build(status, row):
        return "artifact_mismatch"
    state = str(status.get("state") or "")
    if state != "visual_pending":
        if state == "ready":
            return await _confirm_ready_artifact(session, status, row)
        return "artifact_invalid" if state in {"failed", "cancelled"} else "unavailable"
    if _matching_artifact(status, row) is None:
        return "artifact_mismatch"
    if await document_audit_attempts.attestation_pending(session, row):
        return "unavailable"

    attempt = await document_audit_attempts.begin(session, row)
    await session.commit()
    attempt_id = uuid.UUID(str(attempt["id"]))
    usage = attempt.get("usage_envelope") if isinstance(attempt.get("usage_envelope"), dict) else {}
    if attempt.get("state") == "started":
        if attempt.get("may_execute") is not True:
            recorded = await recover_started_result(
                config=config, session=session, row=row, ref=ref, attempt_id=attempt_id
            )
            if recorded is None:
                return "unavailable"
        else:
            result = await invoke_fresh_audit(
                config, session, row, ref, attempt_id, audit_document, before_audit
            )
            if result.get("producer_unresolved") is True:
                return "unavailable"
            usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
            failure = audit_failure_code(result)
            recorded = await document_audit_attempts.record_merged_result(
                session,
                attempt_id=attempt_id,
                usage=usage,
                failure_code=failure,
            )
            if recorded is None:
                raise RuntimeError("document_audit_attempt_conflict")
        usage = recorded.usage
        failure = recorded.failure_code
        passed = failure in {"", "attestation_pending"}
        retryable = failure == "audit_unavailable"
        await session.commit()
    else:
        failure = str(attempt.get("failure_code") or "")
        passed = failure in {"", "attestation_pending"}
        retryable = failure == "audit_unavailable"

    charge_id = await _charge_visual_audit(
        config=config,
        pg_connector=pg_connector,
        redis=redis,
        row=row,
        usage=usage,
        attempt_id=attempt_id,
    )
    await document_audit_attempts.settle(
        session,
        attempt_id=attempt_id,
        charge_id=charge_id or "no_usage",
    )
    await session.commit()
    if not passed:
        return "unavailable" if retryable else "artifact_invalid"
    refreshed = await document_build_status(ref, build_id=str(row["build_id"]))
    return await _confirm_ready_artifact(session, refreshed, row)


async def _confirm_ready_artifact(session: Any, status: object, row: dict) -> str:
    if not isinstance(status, dict):
        return "unavailable"
    if not _matching_build(status, row):
        return "artifact_mismatch"
    if status.get("state") != "ready":
        return (
            "artifact_invalid" if status.get("state") in {"failed", "cancelled"} else "unavailable"
        )
    if _matching_artifact(status, row) is None:
        return "artifact_mismatch"
    if await document_audit_attempts.confirm_attestation(session, row):
        await session.commit()
    return "ready"


def _matching_build(status: dict, row: dict) -> bool:
    digest = str(row.get("source_digest") or "")
    return (
        len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and status.get("source_digest") == digest
        and status.get("build_id") == str(row.get("build_id") or "")
    )


def _matching_artifact(status: dict, row: dict) -> dict | None:
    if not _matching_build(status, row):
        return None
    for item in status.get("artifacts") or []:
        if not isinstance(item, dict) or str(item.get("artifact_id")) != str(row["artifact_id"]):
            continue
        if (
            str(item.get("sha256") or "") == str(row["artifact_sha256"])
            and int(item.get("size") or 0) == int(row["artifact_size"])
            and str(item.get("mime_type") or "") == str(row["mime_type"])
        ):
            return item
    return None


async def _attach_generated_file(session: Any, row: dict, file_id: uuid.UUID) -> None:
    """Add a safe Library reference to the originating assistant turn."""

    if not row.get("assistant_message_id"):
        return
    # PDF and source-bundle jobs hold distinct outbox leases, but share this
    # message projection. Serialize its read/merge/write in the same delivery
    # transaction so one artifact cannot overwrite another's safe reference.
    # An internal target ID is not ownership: require the original owner/thread
    # and an assistant sender before reading or changing its metadata.
    result = await session.execute(
        text(
            "SELECT m.id, m.metadata FROM profile.chat_messages m "
            "JOIN profile.chat_threads t ON t.id=m.thread_id "
            "WHERE m.id=:id AND t.user_id=:user_id AND t.thread_id=:thread_id "
            "AND m.sender IN ('assistant', 'agent') FOR UPDATE OF m"
        ),
        {
            "id": row["assistant_message_id"],
            "user_id": row["user_id"],
            "thread_id": str(row["thread_id"]),
        },
    )
    message = result.mappings().first()
    if not message:
        return
    metadata = dict(message.get("metadata") or {})
    generated = [
        entry for entry in metadata.get("generated_files") or [] if isinstance(entry, dict)
    ]
    if any(str(entry.get("file_id")) == str(file_id) for entry in generated):
        return
    generated.append(
        {
            "kind": "document" if row["role"] == "pdf" else "source_bundle",
            "file_id": str(file_id),
            "filename": str(row["filename"]),
            "mime_type": str(row["mime_type"]),
        }
    )
    metadata["generated_files"] = generated[:16]
    if row["role"] == "pdf":
        metadata["document_outcome"] = "completed"
        metadata["execution_status"] = "completed"
        metadata.pop("document_failure_code", None)
        metadata.pop("document_project_saved", None)
    await session.execute(
        text("UPDATE profile.chat_messages SET metadata=CAST(:metadata AS JSONB) WHERE id=:id"),
        {"metadata": json.dumps(metadata), "id": message["id"]},
    )


async def _finalize_saved_file(session: Any, redis: Any, row: dict, file_id: uuid.UUID) -> str:
    """Attach and announce a committed file only under the current outbox lease."""
    owned = False
    if row.get("lease_token") is not None:
        owned = await document_publications.delivered(
            session,
            job_id=uuid.UUID(str(row["id"])),
            lease_token=uuid.UUID(str(row["lease_token"])),
            file_id=file_id,
        )
    if not owned:
        # Reuse the independently committed file on the next owned attempt.
        completed = await document_publications.delivery_completed(
            session, row=row, file_id=file_id
        )
        await session.rollback()
        return "delivered" if completed else "deferred"
    await _attach_generated_file(session, row, file_id)
    await session.commit()
    from service.services.chat.application.workspace_event_projection import (
        publish_workspace_invalidation,
    )

    try:
        await publish_workspace_invalidation(
            redis,
            thread_id=str(row["thread_id"]),
            action="library_changed",
            revision_changed=False,
        )
    except Exception:
        # REST/outbox remain authoritative after commit. A transport notification
        # failure cannot rewind an already delivered file.
        logger.warning(
            "document publication notification deferred",
            extra={"component": "document_publication", "failure_code": "unavailable"},
        )
    return "delivered"


async def _defer_terminal_publication(session: Any, row: dict, failure_code: str) -> str:
    """Report terminal only for an owned outbox transition, never a stale observation."""
    owned = await document_publications.defer(
        session,
        job_id=uuid.UUID(str(row["id"])),
        lease_token=(uuid.UUID(str(row["lease_token"])) if row.get("lease_token") else None),
        failure_code=failure_code,
        terminal=True,
    )
    if not owned:
        await session.rollback()
        return "deferred"
    return "terminal"


async def deliver_one(
    *,
    config: Any,
    pg_connector: Any,
    redis: Any,
    file_service: Any,
    session: Any,
    row: dict,
) -> str:
    """Deliver one leased row and return a bounded outcome."""

    job_id = uuid.UUID(str(row["id"]))
    raw_lease_token = row.get("lease_token")
    lease_token = uuid.UUID(str(raw_lease_token)) if raw_lease_token is not None else None
    try:
        await _settle_pending_audit(
            config=config, pg_connector=pg_connector, redis=redis, session=session, row=row
        )
        if not await reconcile_started_audit(
            config,
            pg_connector,
            redis,
            session,
            row,
            _settle_pending_audit,
        ):
            return "deferred"
        saved_file_id = await document_publications.saved_file_id(session, row)
        if saved_file_id is not None:
            return await _finalize_saved_file(session, redis, row, saved_file_id)
        if lease_token is None:
            await session.rollback()
            return "deferred"
        binding = await read_binding(redis, str(row["thread_id"]))
        if not binding or str(binding.get("workspace_id")) != str(row["workspace_id"]):
            return await _defer_terminal_publication(session, row, "workspace_expired")
        ref = _agent_ref(binding, row)
        async with _renewing_publication_lease(pg_connector, row) as lease_lost:
            if lease_lost.is_set():
                return "deferred"
            audit_state = await _ensure_audited_durable(
                config=config,
                pg_connector=pg_connector,
                redis=redis,
                session=session,
                ref=ref,
                row=row,
                before_audit=partial(require_publication_lease, pg_connector, row, lease_lost),
            )
            if lease_lost.is_set():
                return "deferred"
        if audit_state != "ready":
            terminal = audit_state in document_publications.TERMINAL_CODES
            if terminal:
                return await _defer_terminal_publication(session, row, audit_state)
            await document_publications.defer(
                session,
                job_id=job_id,
                lease_token=lease_token,
                failure_code=audit_state,
                terminal=terminal,
            )
            return "deferred"
        status = await document_build_status(ref, build_id=str(row["build_id"])) or {}
        if not _matching_artifact(status, row):
            return await _defer_terminal_publication(session, row, "artifact_mismatch")
        async with _renewing_publication_lease(pg_connector, row) as lease_lost:
            if lease_lost.is_set():
                return "deferred"
            download = await stream_document_artifact(
                ref, build_id=str(row["build_id"]), artifact_id=str(row["artifact_id"])
            )
            intent = document_publications.upload_intent(row)
            try:
                # The saver may reject a yielded chunk before exhausting this
                # iterator. Join its watcher/source now, not during later GC.
                async with aclosing(lease_checked_chunks(download.chunks(), lease_lost)) as chunks:
                    saved = await file_service.save_stream(
                        uuid.UUID(str(row["user_id"])),
                        ServiceType.CHAT,
                        str(row["filename"]),
                        chunks,
                        expected_size=int(row["artifact_size"]),
                        expected_sha256=str(row["artifact_sha256"]),
                        upload_intent_id=intent,
                        before_persist=partial(
                            require_publication_lease, pg_connector, row, lease_lost
                        ),
                    )
            finally:
                await download.close()
            if lease_lost.is_set():
                return "deferred"
        return await _finalize_saved_file(session, redis, row, saved.file_id)
    except PublicationLeaseLost:
        await session.rollback()
        # Only the current holder may schedule delivery or change its retry state.
        return "deferred"
    except (DocumentArtifactMissing, document_publications.PublicationArtifactMismatch):
        await session.rollback()
        return await _defer_terminal_publication(session, row, "artifact_mismatch")
    except WorkspaceGone:
        await session.rollback()
        return await _defer_terminal_publication(session, row, "workspace_expired")
    except (WorkspaceUnavailable, OSError, ValueError):
        await session.rollback()
        await document_publications.defer(
            session,
            job_id=job_id,
            lease_token=lease_token,
            failure_code="unavailable",
        )
        return "deferred"
    except Exception:  # noqa: BLE001 - lease is always released through bounded retry
        logger.warning(
            "document publication deferred",
            extra={"component": "document_publication", "failure_code": "unavailable"},
        )
        # Discard an uncommitted delivered CAS/metadata and clear an aborted DB
        # transaction before scheduling retry. Already committed audit usage and
        # independently saved upload-intent files remain durable and reusable.
        await session.rollback()
        await document_publications.defer(
            session,
            job_id=job_id,
            lease_token=lease_token,
            failure_code="unavailable",
        )
        return "deferred"


__all__ = ["deliver_one"]
