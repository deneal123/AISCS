"""Recover a stopped task's identity only for receipt settlement, never dispatch."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness.cancellation import (
    cancelled_projection,
)


async def restored_cancellation(session, request, state, payload):
    task_id = payload.get("_harness_task_v1")
    if task_id is None:
        return None
    row = (
        (
            await session.execute(
                text(
                    "SELECT fencing_epoch FROM profile.harness_task "
                    "WHERE task_id=:task AND active_job_id=:job AND user_id=:owner "
                    "AND thread_id=:thread AND execution_attempt_id=:attempt FOR UPDATE"
                ),
                {
                    "task": UUID(task_id),
                    "job": UUID(request.job_id),
                    "owner": UUID(str(request.user_id)),
                    "thread": UUID(request.thread_id),
                    "attempt": UUID(state.execution_attempt_id),
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise JobStateUnavailable("Cancelled harness identity unavailable")
    state.harness_task_id = task_id
    state.harness_epoch = row["fencing_epoch"]
    return await cancelled_projection(session, request, state)
