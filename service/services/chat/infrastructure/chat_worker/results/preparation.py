"""Prepare accepted turn content before settlement and public turn persistence.

This stage owns terminal usage validation, the result/attempt fence, canonical
acceptance, artifact materialization and the existing prepared-result checkpoint.
Checkpoint hooks retain their durable commit boundaries. This is not a second
transaction coordinator: it neither charges nor commits/publishes the chat turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from service.services.chat.application.error_handling import normalize_response_metadata
from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
    require_terminal_usage,
)
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results.artifacts import persist_all_artifacts
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    PreparedRunContext,
    WorkerExecutionHooks,
    WorkerRunRequest,
)


@dataclass(frozen=True, slots=True, repr=False)
class PreparedTurnContent:
    """Private display projection; no pricing inputs or settlement authority."""

    reply: str
    metadata: dict[str, Any]
    file_url: str | None
    resolved_model: str | None


async def prepare_turn_content(
    request: WorkerRunRequest,
    execution_result: dict[str, Any],
    prepared: PreparedRunContext | None,
    *,
    redis_client: Any,
    publisher: Any,
    job_repo: Any,
    file_service: Any,
    session: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    started_at: float,
) -> PreparedTurnContent:
    """Reuse restored content or prepare one fresh result under its current fence."""
    restored = state.restored_result
    if restored is None:
        require_terminal_usage(execution_result, state.usage_journal)
    if restored is not None:
        reply, metadata = restored["reply"], dict(restored["metadata"])
        file_url = restored["file_url"]
    else:
        reply, metadata = hooks.reply_or_provider_failure(execution_result)
        if "_human_question_pause_v1" in execution_result:
            # Keep the private terminal frame immutable; journal/public projection
            # owns a separate metadata copy, including on an uncertain commit.
            metadata = dict(metadata)
        from service.services.chat.infrastructure.chat_worker.continuation.confirmation import (
            anchor_pending_offer,
        )

        metadata = await anchor_pending_offer(redis_client, request, metadata)
    state.phase.advance(RunPhase.RESULT_LATCHED)
    terminal_task = metadata.get("task_result") or {}
    terminal_cancelled = (
        terminal_task.get("schema_version") == 2 and terminal_task.get("status") == "cancelled"
    )
    if state.harness_task_id and (state.cancelled_execution or terminal_cancelled):
        from service.services.chat.infrastructure.chat_worker.harness.cancellation import (
            cancelled_projection,
        )

        metadata = {
            **metadata,
            "task_result": await cancelled_projection(
                session, request, state, terminal_cancelled=terminal_cancelled
            ),
        }
    resolved_model = execution_result["resolved_model"]
    from service.services.chat.infrastructure.chat_worker.harness.recovery import (
        verify_harness_attempt,
    )

    await verify_harness_attempt(session, request, state)
    if restored is None:
        from service.services.chat.infrastructure.chat_worker.harness.finalization import (
            project_current_result,
            protect_displayed_reply,
        )

        canonical_reply = reply
        reported_metadata = metadata
        metadata = await project_current_result(session, request, state, metadata)
        capture_accepted = getattr(hooks.prepared_results, "capture_accepted", None)
        if capture_accepted is not None:
            await capture_accepted(
                request=request,
                session=session,
                repository=job_repo,
                state=state,
                execution_result=execution_result,
                reply=canonical_reply,
                metadata=metadata,
                prepared=prepared,
                started_at=started_at,
            )
        publisher.publish_payload(
            {
                "type": "stream_complete",
                "job_id": request.job_id,
                "metadata": {
                    "chunks": execution_result["reply_parts_count"],
                    "reply_chars": execution_result["reply_chars_count"],
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        file_url, metadata = await persist_all_artifacts(
            file_service,
            request.user_id,
            metadata,
            request.job_id,
            state.engine_env,
            execution_result,
            request.text,
        )
        metadata = normalize_response_metadata(
            metadata,
            selected_model=resolved_model or request.selected_model,
        )
        from service.infrastructure.agents_client.required_artifacts import delivery_reply

        reply = delivery_reply(reply, metadata, execution_result)
        protected_reply = protect_displayed_reply(canonical_reply, reported_metadata, metadata)
        if protected_reply != canonical_reply:
            reply = protected_reply
            if "ide_summary" in metadata:
                metadata["ide_summary"] = reply
        assert prepared is not None
        await hooks.record_catalog_events(
            session,
            observations=prepared.workflow_observations,
            executions=prepared.workflow_executions,
            thread_id=request.thread_id,
            user_id=str(request.user_id) if request.user_id is not None else None,
            reply=reply,
        )
        if hooks.prepared_results is not None:
            await hooks.prepared_results.capture(
                request=request,
                session=session,
                repository=job_repo,
                state=state,
                execution_result=execution_result,
                reply=reply,
                metadata=metadata,
                file_url=file_url,
                started_at=started_at,
                canonical_reply=canonical_reply,
            )
    return PreparedTurnContent(reply, metadata, file_url, resolved_model)
