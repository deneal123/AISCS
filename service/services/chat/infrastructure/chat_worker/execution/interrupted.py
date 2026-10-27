"""Исчерпанная доставка завершает только сохранённые факты, не запускает модель."""

from collections.abc import Awaitable, Callable
from typing import Any

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.preflight import (
    abort_unverified_job,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerExecutionHooks,
    WorkerRunRequest,
)
from service.services.chat.persistence.harness.retry import MAX_RETRIES


async def finish_exhausted_delivery(
    result: dict[str, Any],
    *,
    request: WorkerRunRequest,
    state: MutableRunState,
    hooks: WorkerExecutionHooks,
    finalize: Callable[..., Awaitable[dict[str, Any]]],
    services: dict[str, Any],
) -> dict[str, Any]:
    if result.get("status") != "error" or result.get("recovery_retry_count") != MAX_RETRIES:
        return result
    try:
        if hooks.prepared_results is None:
            return result
        restored = await hooks.prepared_results.restore(
            request=request,
            repository=services["job_repo"],
            session=services["session"],
            state=state,
            file_service=services["file_service"],
            catalog_recorder=hooks.record_catalog_events,
            redis_client=services["redis_client"],
        )
        if not restored or state.restored_result is None:
            raise JobStateUnavailable("Harness exhaustion checkpoint unavailable")
        saved = state.restored_result
        execution = {
            **saved["usage"],
            "reply": saved["reply"],
            "metadata": saved["metadata"],
            "resolved_model": saved["resolved_model"],
        }
        return await finalize(request, execution, None, state=state, hooks=hooks, **services)
    except Exception:
        failure = await abort_unverified_job(
            session=services["session"],
            publisher=services["publisher"],
            error=JobStateUnavailable("Harness exhaustion reconciliation required"),
            job_id=request.job_id,
        )
        return {**failure, **({"metadata": result["metadata"]} if "metadata" in result else {})}
