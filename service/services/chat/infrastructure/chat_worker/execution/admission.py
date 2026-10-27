"""Composition boundary admitting one owner before worker execution starts."""

from __future__ import annotations

from typing import Any

from service.infrastructure.agents_client.ports import AgentExecutionPort
from service.services.chat.application.error_handling import map_to_worker_error_payload
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_execution_session
from service.services.chat.infrastructure.chat_worker.execution.watchdog import (
    run_with_execution_ownership,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    WorkerExecutionHooks,
    WorkerRunRequest,
)


async def execute_chat_job(
    request: WorkerRunRequest,
    *,
    hooks: WorkerExecutionHooks,
    dependency_factory: Any,
    agent_execution: AgentExecutionPort | None,
) -> dict[str, Any]:
    from service.services.chat.infrastructure.chat_worker.execution.run import _execute_owned_job
    from service.settings import Config

    config = Config()
    connector = dependency_factory.create_pg_connector(config)
    try:
        from service.services.chat.infrastructure.chat_worker.harness.recovery import task_identity

        task_id = await task_identity(connector, request)
        async with claim_execution_session(connector, task_id) as session:
            if session is None:
                return {"status": "processing", "job_id": request.job_id}
            return await run_with_execution_ownership(
                session,
                task_id,
                lambda: _execute_owned_job(
                    request,
                    hooks=hooks,
                    dependency_factory=dependency_factory,
                    agent_execution=agent_execution,
                    config=config,
                    pg_connector=connector,
                ),
            )
    except JobStateUnavailable as exc:
        safe = map_to_worker_error_payload(exc, job_id=request.job_id)
        return {
            "status": "error",
            "error": safe["error"],
            "error_code": safe["error_code"],
            "status_code": safe["status_code"],
        }
