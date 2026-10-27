"""Phase-oriented orchestration for one durable chat worker run."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from service.infrastructure.agents_client.ports import AgentExecutionPort
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.chat.application.error_handling import (
    map_to_worker_error_payload,
)
from service.services.chat.domain.human_questions.resume import RESUME_JOB_KEY
from service.services.chat.infrastructure.agent_context import (
    load_history_items,
    load_memory_parts,
)
from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
    stage_execution_accounting,
)
from service.services.chat.infrastructure.chat_worker.billing.reservation.prepare import (
    _reserve_run,
)
from service.services.chat.infrastructure.chat_worker.context.attachment_evidence import (
    owner_checked_attachments,
)
from service.services.chat.infrastructure.chat_worker.context.turn import (
    collect_engine_inputs,
    message_has_new_file,
    resolve_history_limit,
)
from service.services.chat.infrastructure.chat_worker.execution.admission import execute_chat_job
from service.services.chat.infrastructure.chat_worker.execution.attempt import (
    claim_first_execution,
    commit_preflight,
)
from service.services.chat.infrastructure.chat_worker.execution.dispatch import _execute_agent
from service.services.chat.infrastructure.chat_worker.execution.job_state import (
    HarnessExecutionInterrupted,
    JobStateUnavailable,
)
from service.services.chat.infrastructure.chat_worker.execution.preflight import (
    abort_unverified_job,
)
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results.document_publication import (
    trigger_document_delivery,
)
from service.services.chat.infrastructure.chat_worker.results.events import make_agent_event_handler
from service.services.chat.infrastructure.chat_worker.results.persistence import stage_turn_success
from service.services.chat.infrastructure.chat_worker.results.preparation import (
    prepare_turn_content,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    PreparedRunContext,
    WorkerExecutionHooks,
    WorkerRunRequest,
)
from service.shared.observability.context import set_correlation_context

logger = logging.getLogger(__name__)


async def _prepare_context(
    request: WorkerRunRequest,
    *,
    config: Any,
    pg_connector: Any,
    redis_client: Any,
    session: Any,
    pseudo_session: Any,
    publisher: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    file_service: Any,
) -> PreparedRunContext:
    workflow_observations: list[dict[str, Any]] = []
    workflow_executions: list[dict[str, Any]] = []
    on_event = make_agent_event_handler(
        publisher=publisher,
        job_id=request.job_id,
        streamed_parts=state.streamed_parts,
        workflow_observations=workflow_observations,
        workflow_executions=workflow_executions,
    )
    if request.question_resume is not None:
        from service.services.chat.infrastructure.chat_worker.continuation.resume import (
            build_question_resume_env,
        )

        state.engine_env = await build_question_resume_env(
            request, redis=redis_client, connector=pg_connector
        )
        return PreparedRunContext(
            pseudo_session=pseudo_session,
            file_context="",
            memory_parts=("", ""),
            history_messages=[],
            compact_summary="",
            persona_switched=False,
            tabular_files=[],
            reference_image_url=None,
            has_non_tabular_attachment=False,
            repo_graph_ids=[],
            attachments=[],
            on_event=on_event,
            workflow_observations=workflow_observations,
            workflow_executions=workflow_executions,
        )
    has_new_file = message_has_new_file(request.attachments, request.session_data)
    file_context = request.file_context
    if has_new_file and not file_context.strip():
        file_context = await hooks.recover_attachment_text(
            pg_connector,
            config,
            request.user_id,
        )
    file_context = await hooks.recall_thread_file(
        redis_client,
        request.thread_id,
        file_context,
        has_new_file=has_new_file,
    )
    memory_parts = (
        await load_memory_parts(request.user_id, logger, query=request.text)
        if request.memory_enabled and not state.harness_recovered
        else ("", "")
    )
    history_messages = await load_history_items(
        pseudo_session,
        logger,
        limit_messages=await resolve_history_limit("", config, runtime_settings),
    )
    from service.services.chat.infrastructure.context.summary import summarized_history

    compact_summary, history_messages = await summarized_history(
        items=history_messages,
        session_id=request.thread_id,
        redis_client=redis_client,
    )
    persona_switched = await hooks.resolve_persona_switched(
        db_session=session,
        thread_id=request.thread_id,
        persona_ids=request.persona_ids,
    )
    inputs = await collect_engine_inputs(
        config=config,
        redis_client=redis_client,
        thread_id=request.thread_id,
        user_id=request.user_id,
        attachments=request.attachments,
        session_data=request.session_data,
        has_new_file=has_new_file,
        agent_run_id=request.run_id,
        **(
            {"pg_connector": pg_connector}
            if (request.session_data or {}).get("_ide_context") is not None
            else {}
        ),
    )
    state.engine_env = inputs.engine_env
    safe_attachments = await owner_checked_attachments(
        file_service,
        user_id=request.user_id,
        file_ids=(request.session_data or {}).get("file_ids"),
        attachments=request.attachments,
        redis=redis_client,
    )
    return PreparedRunContext(
        pseudo_session=pseudo_session,
        file_context=file_context,
        memory_parts=memory_parts,
        history_messages=history_messages,
        compact_summary=compact_summary,
        persona_switched=persona_switched,
        tabular_files=inputs.tabular_files,
        reference_image_url=inputs.reference_image_url,
        has_non_tabular_attachment=inputs.has_non_tabular_attachment,
        repo_graph_ids=inputs.repo_graph_ids,
        attachments=safe_attachments,
        on_event=on_event,
        workflow_observations=workflow_observations,
        workflow_executions=workflow_executions,
    )


async def _run_or_restore(
    request: WorkerRunRequest,
    *,
    config: Any,
    pg_connector: Any,
    redis_client: Any,
    publisher: Any,
    job_repo: Any,
    file_service: Any,
    session: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    agent_execution: AgentExecutionPort | None,
) -> tuple[dict[str, Any], PreparedRunContext | None, dict[str, Any] | None]:
    if hooks.prepared_results is not None and await hooks.prepared_results.restore(
        request=request,
        repository=job_repo,
        session=session,
        state=state,
        file_service=file_service,
        catalog_recorder=hooks.record_catalog_events,
        redis_client=redis_client,
    ):
        restored = state.restored_result
        assert restored is not None
        state.phase.advance(RunPhase.RESERVED)
        state.phase.advance(RunPhase.EXECUTING)
        return (
            {
                **restored["usage"],
                "reply": restored["reply"],
                "metadata": restored["metadata"],
                "resolved_model": restored["resolved_model"],
                "reply_parts_count": 0,
                "reply_chars_count": len(restored["reply"]),
            },
            None,
            None,
        )
    from service.services.chat.infrastructure.chat_worker.harness.recovery import recover_harness

    if not await recover_harness(session, request, state):
        state.execution_attempt_id = await claim_first_execution(job_repo, session, request)
    pseudo_session, reservation_result = await _reserve_run(
        request,
        config=config,
        pg_connector=pg_connector,
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        state=state,
        hooks=hooks,
        redis_client=redis_client,
        file_service=file_service,
    )
    if reservation_result is not None:
        return {}, None, reservation_result
    publisher.publish_payload(
        {
            "type": "processing",
            "job_id": request.job_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
    prepared = await _prepare_context(
        request,
        config=config,
        pg_connector=pg_connector,
        redis_client=redis_client,
        session=session,
        pseudo_session=pseudo_session,
        publisher=publisher,
        state=state,
        hooks=hooks,
        file_service=file_service,
    )
    await stage_execution_accounting(job_repo, session, request, state)
    await commit_preflight(session)
    result = await _execute_agent(
        request,
        prepared,
        config=config,
        redis_client=redis_client,
        state=state,
        hooks=hooks,
        agent_execution=agent_execution,
        job_repo=job_repo,
    )
    return result, prepared, None


async def _finalize_success(
    request: WorkerRunRequest,
    execution_result: dict[str, Any],
    prepared: PreparedRunContext | None,
    *,
    config: Any,
    pg_connector: Any,
    redis_client: Any,
    publisher: Any,
    job_repo: Any,
    file_service: Any,
    session: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    started_at: float,
) -> dict[str, Any]:
    content = await prepare_turn_content(
        request,
        execution_result,
        prepared,
        redis_client=redis_client,
        publisher=publisher,
        job_repo=job_repo,
        file_service=file_service,
        session=session,
        state=state,
        hooks=hooks,
        started_at=started_at,
    )
    reply, metadata, file_url = content.reply, content.metadata, content.file_url
    resolved_model = content.resolved_model
    restored = state.restored_result
    from service.services.chat.infrastructure.chat_worker.continuation.pause import (
        verify_question_reference,
    )

    await verify_question_reference(
        request=request, repository=job_repo, session=session, metadata=metadata
    )
    recovery_inputs = {}
    if restored is not None:
        pricing = restored["pricing"]
        recovery_inputs["pricing_inputs"] = (pricing["is_complex"], pricing["tools"])
        started_at -= restored["elapsed_seconds"]
    if (metadata.get("task_result") or {}).get("schema_version") == 2:
        await commit_preflight(session)
    state.charged_credits, metadata = await hooks.charge_and_describe(
        pg_connector=pg_connector,
        redis_client=redis_client,
        config=config,
        execution_result=execution_result,
        session_data=request.session_data,
        metadata=metadata,
        thread_id=request.thread_id,
        job_id=request.job_id,
        user_id=request.user_id,
        resolved_model=resolved_model,
        selected_model=request.selected_model,
        reservation_id=state.reservation_id,
        reserved_estimate=state.reserved_estimate,
        started_at=started_at,
        **recovery_inputs,
    )
    if state.settled_credits > 0:
        metadata.setdefault("usage", {})["credits"] = state.settled_credits + state.charged_credits
    state.phase.advance(RunPhase.CHARGED)
    delivery_wakeup = await stage_turn_success(
        request,
        reply=reply,
        file_url=file_url,
        metadata=metadata,
        engine_env=state.engine_env,
        session=session,
        job_repo=job_repo,
        hooks=hooks,
    )
    await session.commit()
    state.phase.advance(RunPhase.PERSISTED)
    if metadata.get("awaiting_confirmation"):
        publisher.publish_payload(
            {
                "type": "status_update",
                "job_id": request.job_id,
                "message": "Ожидаю решения об использовании платной возможности",
                "metadata": {"kind": "mode_offer", "mode_offer": metadata["mode_offer"]},
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
    if delivery_wakeup:
        trigger_document_delivery()
    await hooks.publish_committed_turn(
        publisher=publisher,
        job_id=request.job_id,
        reply=reply,
        file_url=file_url,
        metadata=metadata,
        run_phase=state.phase,
        memory_enabled=request.memory_enabled,
        extract_memory=hooks.extract_memory,
        memory_kwargs={
            "session": session,
            "pg_connector": pg_connector,
            "redis_client": redis_client,
            "config": config,
            "user_id": request.user_id,
            "thread_id": request.thread_id,
            "job_id": request.job_id,
            "user_text": request.text,
        },
    )
    return {
        "status": "success",
        "job_id": request.job_id,
        "reply": reply,
        "file_url": file_url,
        "metadata": {**metadata, "selected_model": resolved_model or "mws-gpt-alpha"},
    }


async def _cleanup_run(
    *,
    state: MutableRunState,
    request: WorkerRunRequest,
    redis_client: Any,
    publisher: Any,
) -> None:
    try:
        from service.services.chat.infrastructure.chat_worker.engine_env import (
            clear_workspace_active_run,
        )

        await clear_workspace_active_run(state.engine_env, request.run_id, redis_client)
    except Exception:
        logger.debug(
            "workspace active run cleanup failed",
            extra={"component": "workspace", "failure_code": "cleanup"},
        )
    publisher.close()


async def _execute_owned_job(
    request: WorkerRunRequest,
    *,
    hooks: WorkerExecutionHooks,
    dependency_factory: Any,
    agent_execution: AgentExecutionPort | None,
    config: Any,
    pg_connector: Any,
) -> dict[str, Any]:
    """Execute one job through reservation, provider, charging, and durable publication."""

    from service.services.jobs.persistence.job_repository import JobRepository

    set_correlation_context(
        correlation_id=request.job_id,
        trace_id=request.celery_task_id,
    )
    started_at = time.monotonic()
    deps = dependency_factory
    redis_client = deps.create_redis_client(config)
    hooks.bind_runtime_settings(pg_connector)
    await hooks.sync_provider_keys()
    publisher = hooks.publisher_factory(
        redis_client=redis_client,
        stream_key=f"chat:{request.thread_id}:stream",
    )
    job_repo = JobRepository(pg_connector)

    async with pg_connector.get_session_context() as session:
        state = MutableRunState()
        try:
            redelivery = await hooks.redelivery_short_circuit(
                job_repo,
                request.job_id,
                session,
                request.user_id,
            )
            if redelivery is not None:
                return redelivery
            from service.services.chat.infrastructure.chat_worker.continuation.resume import (
                hydrate_question_resume,
            )

            request = await hydrate_question_resume(
                request, connector=pg_connector, config=config, session=session
            )
            # Storage initialization can fail transiently (e.g. bucket discovery).
            # It must use the normal terminal/failure seam rather than escape
            # before the guarded run and leave an unobservable PROCESSING job.
            file_service = hooks.build_file_service(config, pg_connector)
            execution_result, prepared, reservation_result = await _run_or_restore(
                request,
                config=config,
                pg_connector=pg_connector,
                publisher=publisher,
                job_repo=job_repo,
                session=session,
                state=state,
                hooks=hooks,
                redis_client=redis_client,
                file_service=file_service,
                agent_execution=agent_execution,
            )
            if reservation_result is not None:
                return reservation_result
            return await _finalize_success(
                request,
                execution_result,
                prepared,
                config=config,
                pg_connector=pg_connector,
                redis_client=redis_client,
                publisher=publisher,
                job_repo=job_repo,
                file_service=file_service,
                session=session,
                state=state,
                hooks=hooks,
                started_at=started_at,
            )
        except HarnessExecutionInterrupted:
            from service.services.chat.infrastructure.chat_worker.harness.interruption import (
                recover_interrupted_run,
            )

            recovery = await recover_interrupted_run(
                connector=pg_connector,
                session=session,
                request=request,
                state=state,
                publisher=publisher,
            )
            from service.services.chat.infrastructure.chat_worker.execution.interrupted import (
                finish_exhausted_delivery,
            )

            return await finish_exhausted_delivery(
                recovery,
                request=request,
                state=state,
                hooks=hooks,
                finalize=_finalize_success,
                services={
                    "config": config,
                    "pg_connector": pg_connector,
                    "redis_client": redis_client,
                    "publisher": publisher,
                    "job_repo": job_repo,
                    "file_service": file_service,
                    "session": session,
                    "started_at": started_at,
                },
            )
        except JobStateUnavailable as exc:
            return await abort_unverified_job(
                session=session, publisher=publisher, error=exc, job_id=request.job_id
            )
        except Exception as exc:
            if state.harness_task_id or state.accepted_captured or state.usage_checkpoint_observed:
                # Accepted usage and recovery data belong to the job, not this
                # delivery attempt. Preserve them and any idempotent charge;
                # recovery must resume materialization/settlement, never model work.
                return await abort_unverified_job(
                    session=session,
                    publisher=publisher,
                    error=JobStateUnavailable("Prepared result unavailable"),
                    job_id=request.job_id,
                )
            await session.rollback()
            await hooks.handle_failure(
                pg_connector=pg_connector,
                config=config,
                job_repo=job_repo,
                publisher=publisher,
                exc=exc,
                job_id=request.job_id,
                thread_id=request.thread_id,
                # The original user turn already anchors an accepted confirmation.
                user_text=(
                    ""
                    if (request.session_data or {}).get("confirmed_offer_id")
                    or request.question_resume is not None
                    or RESUME_JOB_KEY in (request.session_data or {})
                    else request.text
                ),
                user_id=request.user_id,
                reservation_id=state.reservation_id,
                charged_credits=state.charged_credits,
                streamed_parts=state.streamed_parts,
                attachments=request.attachments,
            )
            safe_error = map_to_worker_error_payload(exc, job_id=request.job_id)
            return {
                "status": "error",
                "error": safe_error["error"],
                "error_code": safe_error["error_code"],
                "status_code": safe_error["status_code"],
            }
        finally:
            await _cleanup_run(
                state=state,
                request=request,
                redis_client=redis_client,
                publisher=publisher,
            )


__all__ = [
    "WorkerExecutionHooks",
    "WorkerRunRequest",
    "execute_chat_job",
]
