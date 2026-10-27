"""Attempt-bound private checkpoint ACK before any public stream projection."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    UsageJournal,
    stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


def usage_checkpoint_sink(
    repository: Any,
    request: WorkerRunRequest,
    state: MutableRunState,
) -> Callable[[Any], Awaitable[None]] | None:
    if state.execution_attempt_id is None:
        return None

    async def persist(payload: Any) -> None:
        try:
            if (
                not isinstance(payload, dict)
                or payload.get("attempt_id") != state.execution_attempt_id
            ):
                raise ValueError
            state.usage_checkpoint_observed = True
            journal = UsageJournal.decode(payload)
            async with repository.connector.get_session_context() as session:
                await stage_usage_journal(
                    repository,
                    session,
                    job_id=UUID(request.job_id),
                    owner_id=UUID(str(request.user_id)),
                    thread_id=request.thread_id,
                    payload=payload,
                )
                await session.commit()
            state.usage_checkpointed = True
            state.usage_journal = journal
        except Exception:
            # ACK uncertainty must not authorize refund/model replay or erase
            # already committed canonical usage through failure finalization.
            raise JobStateUnavailable("Usage checkpoint unavailable") from None

    return persist
