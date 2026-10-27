"""Settle acknowledged cancellation from committed ledger facts, never public events."""

import time
from collections.abc import Awaitable
from typing import Any

from service.services.chat.infrastructure.chat_worker.billing.usage.consistency import (
    require_terminal_usage,
)
from service.services.chat.infrastructure.chat_worker.execution.cancellation import CancelledByUser
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import MutableRunState


def cancelled_result(state: MutableRunState, selected_model: str | None) -> dict[str, Any]:
    journal = state.usage_journal
    zero = (
        state.cancelled_without_dispatch
        and state.cancelled_execution
        and state.usage_checkpointed
        and state.execution_attempt_id is not None
    )
    if not zero and (
        journal is None
        or not state.usage_checkpointed
        or journal.attempt_id != state.execution_attempt_id
    ):
        raise JobStateUnavailable("Cancelled usage unavailable")
    # These are read-only projections of acknowledged, attempt-bound receipts.
    # No estimate from a trace event, reservation or unfinished model call is added.
    if zero and journal is not None:
        raise JobStateUnavailable("Cancelled usage mismatch")
    receipts = journal.receipts if journal else ()
    prompt = sum(receipt.prompt for receipt in receipts)
    completion = sum(receipt.completion for receipt in receipts)
    reply = "Выполнение отменено. Уже сохранённые материалы доступны в Работе."
    result = {
        "reply": reply,
        "resolved_model": selected_model or (receipts[-1].model if receipts else None),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "per_call_usage": [receipt.payload() for receipt in receipts],
        "tool_summary": {},
        "metadata": {"execution_status": "partial"},
        "reply_parts_count": 0,
        "reply_chars_count": len(reply),
    }
    require_terminal_usage(result, journal)
    return result


async def settle_cancelled_execution(
    execution: Awaitable[dict[str, Any]], state: MutableRunState, selected_model: str | None
) -> dict[str, Any]:
    try:
        return await execution
    except CancelledByUser:
        if state.usage_journal is None:
            # Pre-acceptance cancellation retains the existing refund path.
            raise
        result = cancelled_result(state, selected_model)
        state.cancelled_execution = True
        return result


async def restore_cancelled_checkpoint(
    service: Any, *, request: Any, repository: Any, session: Any, state: Any, payload: dict
) -> dict | None:
    """An owned SQL cancellation marker permits settlement, not model replay."""
    from uuid import UUID

    from service.services.chat.infrastructure.chat_worker.billing.reservation.recovery import (
        verify_accounting,
    )
    from service.services.chat.infrastructure.chat_worker.billing.usage.journal import UsageJournal
    from service.services.chat.infrastructure.chat_worker.harness.cancelled_usage import (
        restore_cancelled_usage,
    )
    from service.services.chat.infrastructure.chat_worker.results.checkpoint import CHECKPOINT_KEY
    from service.services.jobs.persistence.transitions import EXECUTION_KEY, USAGE_JOURNAL_KEY

    zero = await restore_cancelled_usage(repository, session, request, payload)
    if payload.get("_cancel_requested_v1") is not True or (
        not zero and USAGE_JOURNAL_KEY not in payload
    ):
        return None
    verified = await verify_accounting(session, payload, request)
    if verified is None:
        raise JobStateUnavailable("Cancelled accounting unavailable")
    state.execution_attempt_id = payload.get(EXECUTION_KEY)
    state.usage_journal = None if zero else UsageJournal.decode(payload[USAGE_JOURNAL_KEY])
    state.cancelled_without_dispatch = zero is True
    state.usage_checkpointed = True
    state.cancelled_execution = True
    state.reservation_id = verified.facts.reservation_id
    state.reserved_estimate = verified.facts.reserved_estimate
    result = cancelled_result(state, request.selected_model)
    from service.services.chat.infrastructure.chat_worker.harness.cancelled_restore import (
        restored_cancellation,
    )

    task_result = await restored_cancellation(session, request, state, payload)
    if task_result is not None:
        result["metadata"]["task_result"] = task_result
    await service.capture(
        request=request,
        repository=repository,
        session=session,
        state=state,
        execution_result=result,
        reply=result["reply"],
        metadata=result["metadata"],
        file_url=None,
        started_at=time.monotonic(),
    )
    job = await repository.lock_prepared_turn(
        UUID(request.job_id), UUID(str(request.user_id)), session=session
    )
    if job is None or not isinstance(job.get("payload"), dict):
        raise JobStateUnavailable("Cancelled checkpoint unavailable")
    return job["payload"].get(CHECKPOINT_KEY)
