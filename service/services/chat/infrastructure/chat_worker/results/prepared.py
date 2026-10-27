"""Prepared-result projection and recovery, without another agent invocation."""

from __future__ import annotations

import math
import re
import time
from typing import Any
from uuid import UUID

from sqlalchemy import text

from service.infrastructure.agents_client.ports import resolve_user_uuid
from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.context.metadata import persistable_meta
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    ACCEPTED_KEY,
    CHECKPOINT_KEY,
    PreparedCheckpointInvalid,
    PreparedTurnCheckpoint,
    store_prepared_turn,
)
from service.services.chat.infrastructure.pricing_signals import _pricing_signals

_USAGE_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "per_call_usage",
    "tool_summary",
)
_CALL_FIELDS = frozenset(
    {
        "provider",
        "model",
        "kind",
        "call_id",
        "receipt_id",
        "estimated",
        "prompt",
        "completion",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
)


def _reply_projection(canonical: str, displayed: str, public: dict) -> str | None:
    from service.infrastructure.agents_client.required_artifacts import (
        DELIVERY_DEFERRED_REPLY,
        DELIVERY_READY_REPLY,
    )

    if canonical == displayed:
        return None
    from service.services.chat.infrastructure.chat_worker.harness.finalization import (
        UNVERIFIED_REPLY,
    )
    from service.shared.task_contract import TaskResultV2

    if displayed == UNVERIFIED_REPLY and isinstance(public.get("task_result"), dict):
        try:
            task = TaskResultV2.model_validate(public["task_result"])
        except ValueError:
            raise PreparedCheckpointInvalid("Prepared result unavailable") from None
        if task.status != "completed":
            return "harness_unverified"
    if displayed == DELIVERY_DEFERRED_REPLY and public.get("execution_status") == "deferred":
        return "required_deferred"
    if (
        displayed == DELIVERY_READY_REPLY
        and public.get("generated_files")
        and public.get("execution_status") != "deferred"
    ):
        return "required_ready"
    raise PreparedCheckpointInvalid("Prepared result unavailable")


def _displayed_reply(canonical: str, public: dict, private: dict) -> str:
    from service.infrastructure.agents_client.required_artifacts import (
        DELIVERY_DEFERRED_REPLY,
        DELIVERY_READY_REPLY,
    )

    projection = private.get("reply_projection")
    if projection is None:
        return canonical
    if projection == "harness_unverified":
        from service.services.chat.infrastructure.chat_worker.harness.finalization import (
            UNVERIFIED_REPLY,
        )

        displayed = UNVERIFIED_REPLY
    else:
        displayed = (
            DELIVERY_READY_REPLY if projection == "required_ready" else DELIVERY_DEFERRED_REPLY
        )
    if _reply_projection(canonical, displayed, public) != projection:
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    return displayed


def _safe_files(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for item in metadata.get("generated_files") or []:
        if not isinstance(item, dict) or not item.get("file_id"):
            raise PreparedCheckpointInvalid("Prepared result unavailable")
        UUID(str(item["file_id"]))
        files.append(
            {key: item[key] for key in ("file_id", "filename", "mime_type", "kind") if key in item}
        )
    return files


def _validate_recovery_fields(public: Any, private: Any) -> None:
    """Fail closed before restoring billing/resources from a versioned projection."""
    if (
        not isinstance(public, dict)
        or not isinstance(private, dict)
        or set(private) - {"reply_projection"}
        != {
            "reservation_id",
            "reserved_estimate",
            "workspace_id",
            "expires_at",
            "publications",
            "pricing",
            "elapsed_seconds",
            "primary_file_id",
        }
    ):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    if "reply_projection" in private and private["reply_projection"] not in {
        "required_ready",
        "required_deferred",
        "harness_unverified",
    }:
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    estimate = private["reserved_estimate"]
    if type(estimate) is not int or estimate < 0:
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    if private["reservation_id"] is not None:
        UUID(private["reservation_id"])
    pricing = private["pricing"]
    if (
        not isinstance(pricing, dict)
        or set(pricing) != {"is_complex", "tools"}
        or type(pricing["is_complex"]) is not bool
        or not isinstance(pricing["tools"], list)
        or len(pricing["tools"]) > 128
        or any(
            not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
            for name in pricing["tools"]
        )
    ):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    for name in ("elapsed_seconds", "expires_at"):
        value = private[name]
        if value is None and name == "expires_at":
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise PreparedCheckpointInvalid("Prepared result unavailable")
    workspace = private["workspace_id"]
    if workspace is not None and (
        not isinstance(workspace, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", workspace)
    ):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    publications = private["publications"]
    if (
        not isinstance(publications, list)
        or len(publications) > 4
        or (publications and not workspace)
    ):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    files = _safe_files(public)
    if private["primary_file_id"] is not None and private["primary_file_id"] not in {
        item["file_id"] for item in files
    }:
        raise PreparedCheckpointInvalid("Prepared result unavailable")


def _validate_usage(usage: Any) -> None:
    if not isinstance(usage, dict) or set(usage) - set(_USAGE_FIELDS):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in usage and (type(usage[key]) is not int or usage[key] < 0):
            raise PreparedCheckpointInvalid("Prepared result unavailable")
    calls = usage.get("per_call_usage", [])
    if not isinstance(calls, list):
        raise PreparedCheckpointInvalid("Prepared result unavailable")
    for call in calls:
        if not isinstance(call, dict) or set(call) - _CALL_FIELDS:
            raise PreparedCheckpointInvalid("Prepared result unavailable")
        for key in ("prompt", "completion", "prompt_tokens", "completion_tokens", "total_tokens"):
            if key in call and (type(call[key]) is not int or call[key] < 0):
                raise PreparedCheckpointInvalid("Prepared result unavailable")


class PreparedResultCoordinator:
    """A stateless worker dependency; all accepted state lives in the owned job."""

    async def capture_accepted(self, **values: Any) -> None:
        from service.services.chat.infrastructure.chat_worker.results.early_resume import (
            capture_accepted,
        )

        await capture_accepted(**values)

    async def capture(
        self,
        *,
        request: Any,
        session: Any,
        repository: Any,
        state: Any,
        execution_result: dict,
        reply: str,
        metadata: dict,
        file_url: str | None,
        started_at: float,
        canonical_reply: str | None = None,
    ) -> None:
        public = persistable_meta(metadata, None)
        files = _safe_files(public)
        if "generated_files" in public:
            public["generated_files"] = files
        usage = {key: execution_result[key] for key in _USAGE_FIELDS if key in execution_result}
        usage["per_call_usage"] = [
            {key: value for key, value in call.items() if key in _CALL_FIELDS}
            for call in execution_result.get("per_call_usage") or []
            if isinstance(call, dict)
        ]
        _validate_usage(usage)
        complex_run, tools = _pricing_signals(execution_result)
        ref = state.engine_env.get("workspace_ref") or {}
        private = {
            "reservation_id": state.reservation_id,
            "reserved_estimate": state.reserved_estimate,
            "workspace_id": ref.get("workspace_id"),
            "expires_at": ref.get("expires_at"),
            "publications": metadata.get("_document_publications") or [],
            "pricing": {"is_complex": complex_run, "tools": tools},
            "elapsed_seconds": max(0.0, time.monotonic() - started_at),
            "primary_file_id": files[0]["file_id"] if files and file_url else None,
        }
        canonical = reply if canonical_reply is None else canonical_reply
        projection = _reply_projection(canonical, reply, public)
        if projection is not None:
            private["reply_projection"] = projection
        _validate_recovery_fields(public, private)
        checkpoint = PreparedTurnCheckpoint.create(
            job_id=request.job_id,
            owner_id=str(resolve_user_uuid(request.user_id, anonymous_fallback=True)),
            thread_id=request.thread_id,
            reply=canonical,
            model=execution_result.get("resolved_model"),
            metadata={"public": public, "private": private},
            usage=usage,
        )
        try:
            await store_prepared_turn(repository, session, checkpoint)
            # Catalog observations and the PROCESSING latch share this transaction.
            # Messages/publication jobs are committed together later.
            await session.commit()
            # Reacquire the admission row lock before settlement: either this
            # delivery or a recovering delivery may finalize, never both.
            owned = await repository.lock_prepared_turn(
                UUID(request.job_id),
                resolve_user_uuid(request.user_id, anonymous_fallback=True),
                session=session,
            )
            if (
                owned is None
                or owned["status"] != ProcessingStatus.PROCESSING
                or owned["payload"].get(CHECKPOINT_KEY) != checkpoint.payload()
            ):
                raise JobStateUnavailable("Prepared result unavailable")
        except Exception:
            # Commit failure may be ambiguous; a collision may belong to another
            # delivery. Neither authorizes marking an accepted result as FAILURE.
            raise JobStateUnavailable("Prepared result unavailable") from None

    async def restore(
        self,
        *,
        request: Any,
        repository: Any,
        session: Any,
        state: Any,
        file_service: Any,
        catalog_recorder: Any = None,
        redis_client: Any = None,
    ) -> bool:
        try:
            owner = resolve_user_uuid(request.user_id, anonymous_fallback=True)
            job = await repository.lock_prepared_turn(UUID(request.job_id), owner, session=session)
            if job is None:
                raise JobStateUnavailable("Prepared result unavailable")
            if job["status"] in (ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE):
                # Another delivery finalized after the terminal preflight read.
                # Never reinterpret a terminal job as fresh work.
                raise JobStateUnavailable("Prepared result unavailable")
            if job["status"] != ProcessingStatus.PROCESSING:
                return False
            payload = job["payload"] if isinstance(job["payload"], dict) else {}
            envelope = payload.get(CHECKPOINT_KEY)
            if envelope is None:
                if ACCEPTED_KEY in payload:
                    from service.services.chat.infrastructure.chat_worker.results import (
                        early_resume as early_result_resume,
                    )

                    envelope = await early_result_resume.restore_accepted(
                        request=request,
                        repository=repository,
                        session=session,
                        file_service=file_service,
                        payload=payload,
                        catalog_recorder=catalog_recorder,
                        redis_client=redis_client,
                    )
                else:
                    from service.services.chat.infrastructure.chat_worker.billing.cancelled import (
                        restore_cancelled_checkpoint,
                    )

                    envelope = await restore_cancelled_checkpoint(
                        self,
                        request=request,
                        repository=repository,
                        session=session,
                        state=state,
                        payload=payload,
                    )
                    if envelope is None:
                        from service.services.chat.infrastructure.chat_worker.harness import (
                            exhaustion,
                        )

                        envelope = await exhaustion.restore_exhausted_checkpoint(
                            self,
                            request=request,
                            repository=repository,
                            session=session,
                            state=state,
                            payload=payload,
                        )
                    if envelope is None:
                        return False
            accepted = PreparedTurnCheckpoint.decode(
                envelope,
                job_id=request.job_id,
                owner_id=str(owner),
                thread_id=request.thread_id,
            ).payload()["body"]
            public = accepted["metadata"]["public"]
            private = accepted["metadata"]["private"]
            _validate_recovery_fields(public, private)
            _validate_usage(accepted["usage"])
            from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
                require_stored_usage,
            )

            require_stored_usage(accepted["usage"], payload)
            from ..billing.reservation.recovery import (
                require_reservation_projection,
                verify_accounting,
            )

            accounting = await verify_accounting(session, payload, request)
            require_reservation_projection(accounting, private)
            if ACCEPTED_KEY in payload:
                from service.services.chat.infrastructure.chat_worker.results.accepted import (
                    decode_accepted,
                )

                early = decode_accepted(
                    payload[ACCEPTED_KEY],
                    job_id=request.job_id,
                    owner_id=str(owner),
                    thread_id=request.thread_id,
                ).payload()["body"]
                if any(early[key] != accepted[key] for key in ("reply", "model", "usage")):
                    raise JobStateUnavailable("Prepared result unavailable")
                state.accepted_captured = True
            metadata = dict(public)
            files = []
            for item in public.get("generated_files") or []:
                owned = await file_service.fetch_file_metadata(
                    request.user_id, UUID(item["file_id"])
                )
                url = await file_service.get_presigned_url_by_key(file_key=owned.file_key)
                files.append({**item, "file_url": url})
            if files:
                metadata["generated_files"] = files
            file_url = next(
                (
                    item["file_url"]
                    for item in files
                    if item["file_id"] == private["primary_file_id"]
                ),
                None,
            )
            metadata["_document_publications"] = private["publications"]
            state.reservation_id = private["reservation_id"]
            state.reserved_estimate = private["reserved_estimate"]
            if private["workspace_id"]:
                state.engine_env = {
                    "workspace_ref": {
                        "workspace_id": private["workspace_id"],
                        "expires_at": private["expires_at"],
                        "thread_id": request.thread_id,
                    }
                }
            state.restored_result = {
                "reply": _displayed_reply(accepted["reply"], public, private),
                "metadata": metadata,
                "file_url": file_url,
                "resolved_model": accepted["model"],
                "usage": accepted["usage"],
                "pricing": private["pricing"],
                "elapsed_seconds": private["elapsed_seconds"],
            }
            # Existing charges are display facts, not money owned by this attempt.
            state.settled_credits = int(
                await session.scalar(
                    text(
                        "SELECT COALESCE(sum(CASE "
                        "WHEN metadata ? 'from_subscription' AND metadata ? 'from_topup' "
                        "THEN COALESCE((metadata->>'from_subscription')::bigint,0) "
                        "+ COALESCE((metadata->>'from_topup')::bigint,0) "
                        "ELSE COALESCE((metadata->>'credits')::bigint,0) END),0) "
                        "FROM profile.billing_events "
                        "WHERE user_id=:owner AND event_type='usage' "
                        "AND metadata->>'idempotency_key' IN (:job,:router)"
                    ),
                    {"owner": owner, "job": request.job_id, "router": request.job_id + ":router"},
                )
                or 0
            )
            return True
        except Exception:
            # A corrupt/inaccessible accepted result must not look like a fresh job.
            raise JobStateUnavailable("Prepared result unavailable") from None
