"""Deliver durable child references, with execution idempotency owned by the worker."""

import asyncio
from typing import Any

from service.services.chat.domain.human_questions.resume import RESUME_JOB_KEY


async def dispatch_question_children(repository: Any, queue: Any, *, enabled: bool) -> dict:
    if enabled is not True:
        return {"claimed": 0, "acknowledged": 0, "deferred": 0}
    # @connection owns and commits this claim. Lost commit ACK means no RPC here.
    claims = await repository.claim_pending()
    counts = {"claimed": len(claims), "acknowledged": 0, "deferred": 0}
    for claim in claims:
        try:
            task_id = await asyncio.to_thread(
                queue.enqueue_agent_message,
                job_id=str(claim.job_id),
                thread_id=str(claim.thread_id),
                user_id=str(claim.user_id),
                text="",
                session_data={RESUME_JOB_KEY: str(claim.job_id)},
                _delivery_task_id=claim.task_id,
                queue="agents",
            )
            if task_id != claim.task_id:
                counts["deferred"] += 1
                continue
            if await repository.acknowledge(claim):
                counts["acknowledged"] += 1
            else:
                counts["deferred"] += 1
        except Exception:
            # An uncertain delivery remains pending under its lease. The next
            # poll sends the SAME child/task ID, never recreates the request/job.
            counts["deferred"] += 1
    return counts
