"""One owned sidecar execution, cancellation and harness admission."""

from typing import Any
from uuid import UUID

import httpx

from service.infrastructure.agents_client.errors import AgentRunInterrupted
from service.infrastructure.agents_client.ports import AgentExecutionPort
from service.services.chat.infrastructure.chat_worker.billing.usage.delivery import (
    usage_checkpoint_sink,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import (
    HarnessAdmissionUnavailable,
    HarnessExecutionInterrupted,
    JobStateUnavailable,
)
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    PreparedRunContext,
    WorkerExecutionHooks,
    WorkerRunRequest,
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
    job_repo: Any,
) -> dict[str, Any]:
    from service.infrastructure.agents_client.engine_factory import select_agent_engine
    from service.services.chat.infrastructure.chat_worker.harness.admission import attach_harness
    from service.shared.harness_protocol import HarnessFailure

    try:
        await attach_harness(request, state, job_repo, config, redis_client=redis_client)
    except HarnessFailure as error:
        raise HarnessAdmissionUnavailable(error.code) from None
    except Exception:
        raise JobStateUnavailable("Harness admission unavailable") from None

    execution_service = agent_execution or select_agent_engine(config, user_id=request.user_id)

    async def durable_cancel() -> bool:
        return await job_repo.is_chat_cancel_requested(
            UUID(request.job_id), UUID(str(request.user_id)), request.thread_id
        )

    state.phase.advance(RunPhase.EXECUTING)
    execution = hooks.run_with_cancel(
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
            execution_attempt_id=state.execution_attempt_id,
            on_usage_checkpoint=usage_checkpoint_sink(job_repo, request, state),
        ),
        redis_client=redis_client,
        celery_task_id=request.celery_task_id,
        durable_cancel=durable_cancel,
    )
    from service.services.chat.infrastructure.chat_worker.billing.cancelled import (
        settle_cancelled_execution,
    )

    try:
        if state.harness_task_id:
            from service.services.chat.infrastructure.chat_worker.harness.cancelled_usage import (
                settle_harness_cancellation,
            )

            return await settle_harness_cancellation(execution, job_repo, request, state)
        return await settle_cancelled_execution(execution, state, request.selected_model)
    except (httpx.TransportError, AgentRunInterrupted):
        if not state.harness_task_id:
            raise
        raise HarnessExecutionInterrupted("Harness transport interrupted") from None
