"""Best-effort persistence of private workflow-catalog observations."""

from __future__ import annotations

import logging
from typing import Any

from service.services.chat.infrastructure.feedback_store import feedback_key
from service.services.chat.persistence import workflow_catalog

logger = logging.getLogger(__name__)


async def record_workflow_catalog_events(
    session: Any,
    *,
    observations: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    thread_id: str,
    user_id: str | None,
    reply: str,
) -> None:
    """Persist private catalog signals in a savepoint without blocking chat success."""

    if not observations and not executions:
        return
    try:
        async with session.begin_nested():
            for observed in observations:
                await workflow_catalog.observe(
                    session,
                    steps=list(observed["steps"]),
                    cost_class=str(observed["cost_class"]),
                    request_text=str(observed["request_text"]),
                    user_id=user_id,
                    thread_id=thread_id,
                )
            content_key = feedback_key(reply)
            for execution in executions:
                await workflow_catalog.record_execution(
                    session,
                    workflow_id=str(execution["workflow_id"]),
                    version=int(execution["version"]),
                    thread_id=thread_id,
                    user_id=user_id,
                    content_key=content_key,
                    succeeded=str(execution.get("status") or "") == "succeeded",
                )
    except Exception:
        logger.warning(
            "workflow catalog observation persistence failed",
            extra={"component": "workflow_catalog", "failure_code": "persistence"},
        )


__all__ = ["record_workflow_catalog_events"]
