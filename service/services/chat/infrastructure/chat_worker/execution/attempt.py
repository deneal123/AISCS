"""Durable no-replay boundary before a job can incur provider or reservation effects."""

from typing import Any
from uuid import UUID, uuid4

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerRunRequest


async def commit_preflight(session: Any) -> None:
    """Release job-row locks before a separate transaction can ACK canonical usage.

    An unknown commit must stop provider execution, not use the normal failure
    path to erase accounting facts or refund an uncertain reservation.
    """
    try:
        await session.commit()
    except Exception:
        raise JobStateUnavailable("Execution preflight unavailable") from None


async def claim_first_execution(repository: Any, session: Any, request: WorkerRunRequest) -> str:
    """One committed attempt, not a retryable lease or an accepted usage receipt.

    An uncertain commit cannot authorize execution. A previous attempt without
    canonical recovery facts requires reconciliation, never blind model replay.
    Accepted/prepared restoration must run before this boundary.
    """
    try:
        attempt = str(uuid4())
        claimed = await repository.claim_chat_execution(
            UUID(request.job_id),
            UUID(str(request.user_id)),
            request.thread_id,
            attempt,
            session=session,
        )
        if claimed is not True:
            raise JobStateUnavailable("Execution attempt unavailable")
        await session.commit()
        return attempt
    except Exception:
        raise JobStateUnavailable("Execution attempt unavailable") from None
