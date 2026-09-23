"""Recoverable Document Forge audit and Library delivery orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from typing import Any

from sqlalchemy import text

from service.infrastructure.agents_client.document_audit import audit_document
from service.infrastructure.workspace_client import (
    DocumentArtifactMissing,
    WorkspaceGone,
    WorkspaceUnavailable,
    document_build_status,
    read_binding,
    stream_document_artifact,
)
from service.models.key_value import ServiceType
from service.services.chat.application.workspace_collaboration import mint_capability
from service.services.chat.persistence import document_audit_attempts, document_publications

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _renewing_publication_lease(pg_connector: Any, row: dict):
    """Keep long audit/upload work owned; signal loss without leaking row details."""

    stop = asyncio.Event()
    lost = asyncio.Event()

    async def heartbeat() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=40)
                return
            except TimeoutError:
                pass
            try:
                async with pg_connector.get_session_context() as heartbeat_session:
                    owned = await document_publications.renew(
                        heartbeat_session,
                        job_id=uuid.UUID(str(row["id"])),
                        lease_token=uuid.UUID(str(row["lease_token"])),
                    )
                    await heartbeat_session.commit()
                if not owned:
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    task = asyncio.create_task(heartbeat())
    try:
        yield lost
    finally:
        stop.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


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
    from service.services.chat.infrastructure.chat_worker.charging import _charge_usage

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
    )
    return str(result) if result is not None else "settled"


async def _ensure_audited_durable(
    *,
    config: Any,
    pg_connector: Any,
    redis: Any,
    session: Any,
    ref: dict,
    row: dict,
) -> str:
    """Persist and settle every accepted deferred visual call before delivery decisions."""

    status = await document_build_status(ref, build_id=str(row["build_id"]))
    if not isinstance(status, dict):
        return "workspace_expired"
    state = str(status.get("state") or "")
    if state != "visual_pending":
        if state == "ready":
            return "ready"
        return "artifact_invalid" if state in {"failed", "cancelled"} else "unavailable"

    attempt = await document_audit_attempts.begin(session, row)
    await session.commit()
    attempt_id = uuid.UUID(str(attempt["id"]))
    usage = attempt.get("usage_envelope") if isinstance(attempt.get("usage_envelope"), dict) else {}
    retryable = False
    passed = False
    if attempt.get("state") == "started":
        result = await audit_document(config, workspace_ref=ref, build_id=str(row["build_id"]))
        usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
        passed = bool(result.get("passed"))
        retryable = bool(result.get("retryable"))
        failure = "" if passed else "audit_unavailable" if retryable else "audit_failed"
        await document_audit_attempts.record_result(
            session,
            attempt_id=attempt_id,
            usage=usage,
            failure_code=failure,
        )
        await session.commit()
    else:
        failure = str(attempt.get("failure_code") or "")
        passed = not failure
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
    if isinstance(refreshed, dict) and refreshed.get("state") == "ready":
        return "ready"
    return "unavailable"


def _matching_artifact(status: dict, row: dict) -> dict | None:
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
    result = await session.execute(
        text("SELECT id, metadata FROM profile.chat_messages WHERE id=:id"),
        {"id": row["assistant_message_id"]},
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
    lease_token = uuid.UUID(str(row["lease_token"]))
    try:
        binding = await read_binding(redis, str(row["thread_id"]))
        if not binding or str(binding.get("workspace_id")) != str(row["workspace_id"]):
            await document_publications.defer(
                session,
                job_id=job_id,
                lease_token=lease_token,
                failure_code="workspace_expired",
                terminal=True,
            )
            return "terminal"
        ref = _agent_ref(binding, row)
        async with _renewing_publication_lease(pg_connector, row) as lease_lost:
            audit_state = await _ensure_audited_durable(
                config=config,
                pg_connector=pg_connector,
                redis=redis,
                session=session,
                ref=ref,
                row=row,
            )
            if lease_lost.is_set():
                return "deferred"
        if audit_state != "ready":
            terminal = audit_state in document_publications.TERMINAL_CODES
            await document_publications.defer(
                session,
                job_id=job_id,
                lease_token=lease_token,
                failure_code=audit_state,
                terminal=terminal,
            )
            return "terminal" if terminal else "deferred"
        status = await document_build_status(ref, build_id=str(row["build_id"])) or {}
        if not _matching_artifact(status, row):
            await document_publications.defer(
                session,
                job_id=job_id,
                lease_token=lease_token,
                failure_code="artifact_mismatch",
                terminal=True,
            )
            return "terminal"
        async with _renewing_publication_lease(pg_connector, row) as lease_lost:
            download = await stream_document_artifact(
                ref, build_id=str(row["build_id"]), artifact_id=str(row["artifact_id"])
            )
            intent = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"gpthub-document:{row['user_id']}:{row['build_id']}:{row['artifact_id']}:{row['role']}",
            )
            try:
                saved = await file_service.save_stream(
                    uuid.UUID(str(row["user_id"])),
                    ServiceType.CHAT,
                    str(row["filename"]),
                    download.chunks(),
                    expected_size=int(row["artifact_size"]),
                    expected_sha256=str(row["artifact_sha256"]),
                    upload_intent_id=intent,
                )
            finally:
                await download.close()
            if lease_lost.is_set():
                return "deferred"
        await document_publications.delivered(
            session,
            job_id=job_id,
            lease_token=lease_token,
            file_id=saved.file_id,
        )
        await _attach_generated_file(session, row, saved.file_id)
        await session.commit()
        from service.services.chat.application.workspace_event_projection import (
            publish_workspace_invalidation,
        )

        await publish_workspace_invalidation(
            redis,
            thread_id=str(row["thread_id"]),
            action="library_changed",
            revision_changed=False,
        )
        return "delivered"
    except DocumentArtifactMissing:
        await document_publications.defer(
            session,
            job_id=job_id,
            lease_token=lease_token,
            failure_code="artifact_mismatch",
            terminal=True,
        )
        return "terminal"
    except WorkspaceGone:
        await document_publications.defer(
            session,
            job_id=job_id,
            lease_token=lease_token,
            failure_code="workspace_expired",
            terminal=True,
        )
        return "terminal"
    except (WorkspaceUnavailable, OSError, ValueError):
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
        await document_publications.defer(
            session,
            job_id=job_id,
            lease_token=lease_token,
            failure_code="unavailable",
        )
        return "deferred"


__all__ = ["deliver_one"]
