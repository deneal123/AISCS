"""Celery entrypoints and compatibility facade for durable chat execution.

Business phases live under :mod:`chat_worker`; this module intentionally keeps
the historical task names and private monkeypatch seams used by rolling workers
and the regression suite.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

from service.infrastructure.agents_client.ports import AgentExecutionPort
from service.services.chat.infrastructure.chat_worker import (
    ChatWorkerDependencyFactory,
    WorkerStreamPublisherService,
)
from service.services.chat.infrastructure.chat_worker import (
    build_file_service as _build_file_service,
)
from service.services.chat.infrastructure.chat_worker.attachment_recovery import (
    recover_attachment_text,
)
from service.services.chat.infrastructure.chat_worker.cancellation import (
    CancelledByUser as CancelledByUser,
)
from service.services.chat.infrastructure.chat_worker.cancellation import (
    run_with_cancel as _run_with_cancel,
)
from service.services.chat.infrastructure.chat_worker.catalog_events import (
    record_workflow_catalog_events,
)
from service.services.chat.infrastructure.chat_worker.charging import (
    _charge_memory_usage,
    _overlay_billing,
    _release_reservation,
)
from service.services.chat.infrastructure.chat_worker.failure import handle_worker_failure
from service.services.chat.infrastructure.chat_worker.job_state import (
    fetch_job_status,
    mark_job_failed_committed,
    redelivery_short_circuit,
    update_job_status,
)
from service.services.chat.infrastructure.chat_worker.memory_maintenance import (
    MemoryUserUnresolved,
    extract_and_charge_memory,
    maybe_compact_thread,
    resolve_memory_user_id,
    restore_pseudo_session_history,
)
from service.services.chat.infrastructure.chat_worker.message_meta import (
    persona_switched as resolve_persona_switched,
)
from service.services.chat.infrastructure.chat_worker.message_meta import (
    reply_or_provider_failure as _reply_or_provider_failure,
)
from service.services.chat.infrastructure.chat_worker.message_meta import user_message_meta
from service.services.chat.infrastructure.chat_worker.publication import publish_committed_turn
from service.services.chat.infrastructure.chat_worker.reservation import (
    emit_expensive_confirmation,
    emit_insufficient_credits,
    estimate_reservation_credits,
    reservation_context_chars,
    reserve_credits_or_short_circuit,
)
from service.services.chat.infrastructure.chat_worker.retention import delete_expired_chat_history
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    WorkerExecutionHooks,
    WorkerRunRequest,
)
from service.services.chat.infrastructure.chat_worker.run_execution import execute_chat_job
from service.services.chat.infrastructure.chat_worker.runtime_sync import (
    bind_runtime_settings as _bind_runtime_settings,
)
from service.services.chat.infrastructure.chat_worker.runtime_sync import (
    sync_provider_keys as _sync_provider_keys,
)
from service.services.chat.infrastructure.chat_worker.task_runtime import run_coroutine
from service.services.chat.infrastructure.chat_worker.thread_file_context import (
    recall_or_persist_thread_file,
)
from service.services.chat.infrastructure.chat_worker.turn_result import (
    _persist_chat_turn,
    _persist_partial_turn_committed,
    charge_and_describe,
)

logger = logging.getLogger(__name__)

_recall_or_persist_thread_file = recall_or_persist_thread_file
_MemoryUserUnresolved = MemoryUserUnresolved


async def _fetch_job_status_with_session(job_repo, job_id: str, session, user_id):
    return await fetch_job_status(job_repo, job_id, session, user_id)


async def _update_job_status_with_session(
    job_repo, job_id: str, status, session, user_id, result_data: dict | None = None
):
    await update_job_status(job_repo, job_id, status, session, user_id, result_data)


async def _mark_job_failed_committed(pg_connector, job_repo, job_id: str, user_id) -> None:
    await mark_job_failed_committed(
        pg_connector,
        job_repo,
        job_id,
        user_id,
        update_status=_update_job_status_with_session,
    )


async def _record_workflow_catalog_events(
    session,
    *,
    observations: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    thread_id: str,
    user_id: str | None,
    reply: str,
) -> None:
    await record_workflow_catalog_events(
        session,
        observations=observations,
        executions=executions,
        thread_id=thread_id,
        user_id=user_id,
        reply=reply,
    )


async def _handle_worker_failure(
    *,
    pg_connector,
    config,
    job_repo,
    publisher,
    exc: Exception,
    job_id: str,
    thread_id: str,
    user_text: str,
    user_id: str | None,
    reservation_id: str | None,
    charged_credits: int,
    streamed_parts: list[str],
    attachments: list | None = None,
) -> None:
    await handle_worker_failure(
        pg_connector=pg_connector,
        config=config,
        job_repo=job_repo,
        publisher=publisher,
        exc=exc,
        job_id=job_id,
        thread_id=thread_id,
        user_text=user_text,
        user_id=user_id,
        reservation_id=reservation_id,
        charged_credits=charged_credits,
        streamed_parts=streamed_parts,
        attachments=attachments,
        overlay_billing=_overlay_billing,
        release_reservation=_release_reservation,
        mark_job_failed=_mark_job_failed_committed,
        persist_partial_turn=_persist_partial_turn_committed,
        user_message_metadata=user_message_meta,
    )


async def _resolve_memory_user_id(*, db_session, user_id: Any, thread_id: str) -> str | None:
    return await resolve_memory_user_id(db_session=db_session, user_id=user_id, thread_id=thread_id)


async def _restore_pseudo_session_history(
    *,
    pseudo_session,
    db_session,
    thread_id: str,
    session_data: dict | None,
    history_limit: int = 12,
) -> int:
    return await restore_pseudo_session_history(
        pseudo_session=pseudo_session,
        db_session=db_session,
        thread_id=thread_id,
        session_data=session_data,
        history_limit=history_limit,
    )


async def _maybe_compact_thread(
    *, db_session, redis_client, config, user_id: str, thread_id: str
) -> None:
    await maybe_compact_thread(
        db_session=db_session,
        redis_client=redis_client,
        config=config,
        user_id=user_id,
        thread_id=thread_id,
    )


def _reservation_context_chars(*, file_context, pseudo_session, attachments) -> int:
    return reservation_context_chars(
        file_context=file_context,
        pseudo_session=pseudo_session,
        attachments=attachments,
    )


async def _estimate_reservation_credits(
    *,
    pg_connector,
    billing_cfg,
    text: str,
    selected_model: str | None,
    context_chars: int = 0,
    route: str | None = None,
) -> int:
    return await estimate_reservation_credits(
        pg_connector=pg_connector,
        billing_cfg=billing_cfg,
        text=text,
        selected_model=selected_model,
        context_chars=context_chars,
        route=route,
    )


async def _reserve_credits_or_short_circuit(
    *,
    pg_connector,
    config,
    publisher,
    job_repo,
    session,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    context_chars: int = 0,
    attachments: list | None = None,
    expensive_run_confirmed: bool = False,
    redis_client=None,
    confirmation_context: dict | None = None,
) -> tuple[dict | None, str | None, int]:
    return await reserve_credits_or_short_circuit(
        pg_connector=pg_connector,
        config=config,
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=job_id,
        thread_id=thread_id,
        text=text,
        user_id=user_id,
        selected_model=selected_model,
        context_chars=context_chars,
        attachments=attachments,
        expensive_run_confirmed=expensive_run_confirmed,
        redis_client=redis_client,
        confirmation_context=confirmation_context,
        overlay_billing=_overlay_billing,
        estimate_credits=_estimate_reservation_credits,
        emit_expensive=_emit_expensive_run_confirmation_required,
        emit_insufficient=_emit_insufficient_credits,
    )


async def _emit_expensive_run_confirmation_required(
    *,
    publisher,
    job_repo,
    session,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    estimated_credits: int,
    attachments: list | None = None,
    redis_client=None,
    confirmation_context: dict | None = None,
) -> dict:
    return await emit_expensive_confirmation(
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=job_id,
        thread_id=thread_id,
        text=text,
        user_id=user_id,
        selected_model=selected_model,
        estimated_credits=estimated_credits,
        attachments=attachments,
        redis_client=redis_client,
        confirmation_context=confirmation_context or {},
        persist_turn=_persist_chat_turn,
        update_job_status=_update_job_status_with_session,
    )


async def _emit_insufficient_credits(
    *,
    publisher,
    job_repo,
    session,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    selected_model: str | None,
    reply: str,
    attachments: list | None = None,
) -> dict:
    return await emit_insufficient_credits(
        publisher=publisher,
        job_repo=job_repo,
        session=session,
        job_id=job_id,
        thread_id=thread_id,
        text=text,
        user_id=user_id,
        selected_model=selected_model,
        reply=reply,
        attachments=attachments,
        persist_turn=_persist_chat_turn,
        update_job_status=_update_job_status_with_session,
    )


async def _extract_and_charge_memory(
    *,
    session,
    pg_connector,
    redis_client,
    config,
    user_id: str | None,
    thread_id: str,
    job_id: str,
    user_text: str,
) -> None:
    await extract_and_charge_memory(
        session=session,
        pg_connector=pg_connector,
        redis_client=redis_client,
        config=config,
        user_id=user_id,
        thread_id=thread_id,
        job_id=job_id,
        user_text=user_text,
        resolve_user=_resolve_memory_user_id,
        charge_usage=_charge_memory_usage,
        compact_thread=_maybe_compact_thread,
    )


async def _recover_attachment_text(pg_connector, config, user_id: str | None) -> str:
    return await recover_attachment_text(pg_connector, config, user_id)


async def _redelivery_short_circuit(job_repo, job_id: str, session, user_id) -> dict | None:
    return await redelivery_short_circuit(
        job_repo,
        job_id,
        session,
        user_id,
        fetch_status=_fetch_job_status_with_session,
    )


def _execution_hooks() -> WorkerExecutionHooks:
    """Resolve facade callbacks at call time so monkeypatches remain effective."""

    return WorkerExecutionHooks(
        bind_runtime_settings=_bind_runtime_settings,
        sync_provider_keys=_sync_provider_keys,
        publisher_factory=WorkerStreamPublisherService,
        build_file_service=_build_file_service,
        redelivery_short_circuit=_redelivery_short_circuit,
        update_job_status=_update_job_status_with_session,
        restore_history=_restore_pseudo_session_history,
        reservation_context_chars=_reservation_context_chars,
        reserve_credits=_reserve_credits_or_short_circuit,
        recover_attachment_text=_recover_attachment_text,
        recall_thread_file=_recall_or_persist_thread_file,
        resolve_persona_switched=resolve_persona_switched,
        run_with_cancel=_run_with_cancel,
        reply_or_provider_failure=_reply_or_provider_failure,
        record_catalog_events=_record_workflow_catalog_events,
        charge_and_describe=charge_and_describe,
        persist_chat_turn=_persist_chat_turn,
        publish_committed_turn=publish_committed_turn,
        extract_memory=_extract_and_charge_memory,
        handle_failure=_handle_worker_failure,
    )


async def process_agent_message_async(
    job_id: str,
    thread_id: str,
    text: str,
    user_id: str | None,
    session_data: dict | None = None,
    selected_model: str | None = None,
    route_override: str | None = None,
    input_type: str | None = None,
    web_search: bool = False,
    deep_research: bool = False,
    file_context: str = "",
    attachments: list | None = None,
    memory_enabled: bool = True,
    ldr_model: str | None = None,
    ldr_strategy: str | None = None,
    multi_intent: bool | None = None,
    persona_ids: list[str] | None = None,
    planning: bool | None = None,
    celery_task_id: str | None = None,
    dependency_factory: ChatWorkerDependencyFactory | None = None,
    agent_execution: AgentExecutionPort | None = None,
) -> dict:
    request = WorkerRunRequest.from_mapping(locals())
    return await execute_chat_job(
        request,
        hooks=_execution_hooks(),
        dependency_factory=dependency_factory or ChatWorkerDependencyFactory(),
        agent_execution=agent_execution,
    )


@shared_task(
    bind=True,
    name="service.services.chat.infrastructure.chat_worker_tasks.process_agent_message",
    soft_time_limit=300,
    time_limit=330,
)
def process_agent_message(
    self,
    job_id: str,
    thread_id: str,
    text: str,
    user_id: int,
    session_data: dict | None = None,
    selected_model: str | None = None,
    route_override: str | None = None,
    input_type: str | None = None,
    web_search: bool = False,
    deep_research: bool = False,
    file_context: str = "",
    attachments: list | None = None,
    memory_enabled: bool = True,
    ldr_model: str | None = None,
    ldr_strategy: str | None = None,
    multi_intent: bool | None = None,
    persona_ids: list[str] | None = None,
    planning: bool | None = None,
    **forward_compat,
) -> dict:
    if forward_compat:
        logger.warning(
            "воркер старее backend: задача получила неизвестные поля — они проигнорированы",
            extra={
                "component": "chat_worker",
                "failure_code": "forward_compat",
                "unknown_field_count": len(forward_compat),
            },
        )
    return run_coroutine(
        process_agent_message_async(
            job_id=job_id,
            thread_id=thread_id,
            text=text,
            user_id=str(user_id) if user_id is not None else None,
            session_data=session_data,
            selected_model=selected_model,
            route_override=route_override,
            input_type=input_type,
            web_search=web_search,
            deep_research=deep_research,
            file_context=file_context or "",
            attachments=attachments,
            memory_enabled=memory_enabled,
            ldr_model=ldr_model,
            ldr_strategy=ldr_strategy,
            multi_intent=multi_intent,
            persona_ids=persona_ids,
            planning=planning,
            celery_task_id=getattr(self.request, "id", None),
        )
    )


@shared_task(
    bind=True,
    name="service.services.chat.infrastructure.chat_worker_tasks.delete_old_chat_history",
    time_limit=300,
    soft_time_limit=280,
)
def delete_old_chat_history(self) -> dict:
    del self
    from service.settings import config

    retention_days = int(config.chat_retention_days)
    pg_connector = ChatWorkerDependencyFactory().create_pg_connector(config)
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    run_coroutine(delete_expired_chat_history(pg_connector, cutoff))
    return {"status": "ok", "retention_days": retention_days}
