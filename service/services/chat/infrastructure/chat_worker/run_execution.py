"""Phase-oriented orchestration for one durable chat worker run."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from service.infrastructure.agents_client.ports import AgentExecutionPort
from service.models.key_value import ProcessingStatus
from service.services.admin.application.runtime_settings import runtime_settings
from service.services.chat.application.error_handling import (
    map_to_worker_error_payload,
    normalize_response_metadata,
)
from service.services.chat.infrastructure.agent_context import (
    create_session,
    load_history_items,
    load_memory_parts,
)
from service.services.chat.infrastructure.chat_worker.artifacts import persist_all_artifacts
from service.services.chat.infrastructure.chat_worker.attachment_evidence import (
    owner_checked_attachments,
)
from service.services.chat.infrastructure.chat_worker.message_meta import (
    persistable_meta,
    user_message_meta,
)
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    PreparedRunContext,
    WorkerExecutionHooks,
    WorkerRunRequest,
)
from service.services.chat.infrastructure.chat_worker.stream_events import make_agent_event_handler
from service.services.chat.infrastructure.chat_worker.turn_context import (
    collect_engine_inputs,
    message_has_new_file,
    read_summary_or_empty,
    resolve_history_limit,
)
from service.shared.observability.context import set_correlation_context

logger = logging.getLogger(__name__)


async def _reserve_run(
    request: WorkerRunRequest,
    *,
    config: Any,
    pg_connector: Any,
    publisher: Any,
    job_repo: Any,
    session: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    redis_client: Any,
    file_service: Any,
) -> tuple[Any, dict[str, Any] | None]:
    await hooks.update_job_status(
        job_repo,
        request.job_id,
        ProcessingStatus.PROCESSING,
        session,
        request.user_id,
    )
    confirmed_offer_id = str((request.session_data or {}).get("confirmed_offer_id") or "")
    if confirmed_offer_id:
        from service.services.chat.domain.confirmation_offer import mark_persisted_offer_accepted

        await mark_persisted_offer_accepted(
            session,
            thread_id=request.thread_id,
            offer_id=confirmed_offer_id,
        )
        await session.commit()
    pseudo_session = create_session(
        session_id=(request.session_data or {}).get("session_id", request.thread_id)
    )
    await hooks.restore_history(
        pseudo_session=pseudo_session,
        db_session=session,
        thread_id=request.thread_id,
        session_data=request.session_data,
        history_limit=max(getattr(config.agents, "chat_history_messages_limit", 8), 1),
    )
    safe_attachments = await owner_checked_attachments(
        file_service,
        user_id=request.user_id,
        file_ids=(request.session_data or {}).get("file_ids"),
        attachments=request.attachments,
        redis=redis_client,
    )
    context_chars = hooks.reservation_context_chars(
        file_context=request.file_context,
        pseudo_session=pseudo_session,
        attachments=safe_attachments,
    )
    short_circuit, state.reservation_id, state.reserved_estimate = await hooks.reserve_credits(
        pg_connector=pg_connector,
        config=config,
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=request.job_id,
        thread_id=request.thread_id,
        text=request.text,
        user_id=request.user_id,
        selected_model=request.selected_model,
        context_chars=context_chars,
        attachments=safe_attachments,
        expensive_run_confirmed=bool((request.session_data or {}).get("confirm_expensive_run")),
        redis_client=redis_client,
        confirmation_context={
            "route_override": request.route_override,
            "resolved_category": (request.session_data or {}).get("_resolved_category"),
            "input_type": request.input_type,
            "file_ids": (request.session_data or {}).get("file_ids") or [],
        },
    )
    if short_circuit is not None:
        await session.commit()
        return pseudo_session, short_circuit
    state.phase.advance(RunPhase.RESERVED)
    return pseudo_session, None


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
        if request.memory_enabled
        else ("", "")
    )
    compact_summary = await read_summary_or_empty(request.thread_id, config)
    history_messages = await load_history_items(
        pseudo_session,
        logger,
        limit_messages=await resolve_history_limit(compact_summary, config, runtime_settings),
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


async def _execute_agent(
    request: WorkerRunRequest,
    prepared: PreparedRunContext,
    *,
    config: Any,
    redis_client: Any,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    agent_execution: AgentExecutionPort | None,
) -> dict[str, Any]:
    from service.infrastructure.agents_client.engine_factory import select_agent_engine

    execution_service = agent_execution or select_agent_engine(config, user_id=request.user_id)
    state.phase.advance(RunPhase.EXECUTING)
    return await hooks.run_with_cancel(
        execution_service.execute(
            text=request.text,
            thread_id=request.thread_id,
            user_id=request.user_id,
            session_data=request.session_data,
            selected_model=request.selected_model,
            route_override=request.route_override,
            input_type=request.input_type,
            web_search=request.web_search,
            deep_research=request.deep_research,
            file_context=prepared.file_context,
            attachments=prepared.attachments,
            pseudo_session=prepared.pseudo_session,
            on_event=prepared.on_event,
            memory_enabled=request.memory_enabled,
            ldr_model=request.ldr_model,
            ldr_strategy=request.ldr_strategy,
            multi_intent=request.multi_intent,
            persona_ids=request.persona_ids,
            planning=request.planning,
            persona_switched=prepared.persona_switched,
            memory_parts=prepared.memory_parts,
            history_messages=prepared.history_messages,
            compact_summary=prepared.compact_summary,
            tabular_files=prepared.tabular_files,
            reference_image_url=prepared.reference_image_url,
            repo_graph_ids=prepared.repo_graph_ids,
            has_non_tabular_attachment=prepared.has_non_tabular_attachment,
            **state.engine_env,
        ),
        redis_client=redis_client,
        celery_task_id=request.celery_task_id,
    )


async def _finalize_success(
    request: WorkerRunRequest,
    execution_result: dict[str, Any],
    prepared: PreparedRunContext,
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
    reply, metadata = hooks.reply_or_provider_failure(execution_result)
    state.phase.advance(RunPhase.RESULT_LATCHED)
    resolved_model = execution_result["resolved_model"]
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
    await hooks.record_catalog_events(
        session,
        observations=prepared.workflow_observations,
        executions=prepared.workflow_executions,
        thread_id=request.thread_id,
        user_id=str(request.user_id) if request.user_id is not None else None,
        reply=reply,
    )
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
    )
    state.phase.advance(RunPhase.CHARGED)
    # Delivery descriptors are a private transaction intent.  Remove them before
    # assistant metadata is persisted or published; only the durable outbox row may
    # retain artifact/build digests until Library delivery completes.
    publication_descriptors = metadata.pop("_document_publications", None)
    confirmed_offer = bool((request.session_data or {}).get("confirmed_offer_id"))
    await hooks.persist_chat_turn(
        db_session=session,
        thread_id=request.thread_id,
        user_text="" if confirmed_offer else request.text,
        assistant_text=reply,
        user_id=request.user_id,
        user_metadata={} if confirmed_offer else user_message_meta(request.attachments),
        assistant_metadata=persistable_meta(metadata, file_url),
    )
    workspace_ref = state.engine_env.get("workspace_ref") if state.engine_env else None
    if publication_descriptors and isinstance(workspace_ref, dict):
        from service.infrastructure.agents_client.ports import resolve_user_uuid
        from service.services.chat.persistence.document_publications import enqueue

        await enqueue(
            session,
            user_id=resolve_user_uuid(request.user_id, anonymous_fallback=True),
            thread_id=request.thread_id,
            workspace_id=str(workspace_ref.get("workspace_id") or ""),
            billing_job_id=request.job_id,
            descriptors=tuple(publication_descriptors),
        )
    await hooks.update_job_status(
        job_repo,
        request.job_id,
        ProcessingStatus.SUCCESS,
        session,
        request.user_id,
        {"reply": reply, "file_url": file_url, "metadata": metadata},
    )
    await session.commit()
    state.phase.advance(RunPhase.PERSISTED)
    if publication_descriptors:
        try:
            from service.infrastructure.messaging.tasks import deliver_document_publications

            deliver_document_publications.delay()
        except Exception:
            logger.warning(
                "document publication trigger deferred",
                extra={"component": "document_publication", "failure_code": "unavailable"},
            )
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


async def execute_chat_job(
    request: WorkerRunRequest,
    *,
    hooks: WorkerExecutionHooks,
    dependency_factory: Any,
    agent_execution: AgentExecutionPort | None,
) -> dict[str, Any]:
    """Execute one job through reservation, provider, charging, and durable publication."""

    from service.services.jobs.persistence.job_repository import JobRepository
    from service.settings import Config

    set_correlation_context(
        correlation_id=request.job_id,
        trace_id=request.celery_task_id,
    )
    config = Config()
    started_at = time.monotonic()
    deps = dependency_factory
    pg_connector = deps.create_pg_connector(config)
    redis_client = deps.create_redis_client(config)
    hooks.bind_runtime_settings(pg_connector)
    await hooks.sync_provider_keys()
    publisher = hooks.publisher_factory(
        redis_client=redis_client,
        stream_key=f"chat:{request.thread_id}:stream",
    )
    job_repo = JobRepository(pg_connector)
    file_service = hooks.build_file_service(config, pg_connector)

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
                return reservation_result
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
            execution_result = await _execute_agent(
                request,
                prepared,
                config=config,
                redis_client=redis_client,
                state=state,
                hooks=hooks,
                agent_execution=agent_execution,
            )
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
        except Exception as exc:
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
                    "" if (request.session_data or {}).get("confirmed_offer_id") else request.text
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
