"""Завершение исчерпанного восстановления из receipts, без повторного исполнения."""

import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.billing.reservation.recovery import (
    verify_accounting,
)
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    UsageJournal,
    stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness.cancelled_usage import canonical_usage
from service.services.chat.infrastructure.chat_worker.harness.zero_usage import (
    verified_without_dispatch,
)
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.services.chat.persistence.harness.result import read_result
from service.services.chat.persistence.harness.retry import MAX_RETRIES, RETRY_KEY
from service.services.chat.persistence.harness.state import grant_rows, snapshot
from service.services.jobs.persistence.transitions import (
    EXECUTION_KEY,
    HARNESS_KEY,
    USAGE_JOURNAL_KEY,
)
from service.shared.task_contract import TaskResultV2


def exhausted(payload: dict[str, Any]) -> bool:
    marker = payload.get(RETRY_KEY)
    return (
        isinstance(marker, dict)
        and marker.get("state") == "blocked"
        and type(marker.get("count")) is int
        and marker["count"] == MAX_RETRIES
        and marker.get("attempt_id") == payload.get(EXECUTION_KEY)
        and payload.get("_cancel_requested_v1") is not True
        and HARNESS_KEY in payload
    )


async def _owned_task(session: Any, request: Any, payload: dict[str, Any]) -> Mapping[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.*,j.payload AS job_payload FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id AND j.user_id=t.user_id "
                    "JOIN profile.chat_threads c ON c.thread_id=t.thread_id "
                    "AND c.user_id=t.user_id "
                    "WHERE t.task_id=:task AND t.active_job_id=:job AND t.user_id=:owner "
                    "AND t.thread_id=:thread AND t.execution_attempt_id=:attempt "
                    "AND j.type='CHAT' AND j.status='PROCESSING' "
                    "AND j.payload->>'thread_id'=CAST(CAST(:thread AS uuid) AS text) "
                    "AND j.payload->>'_execution_attempt_v1'=CAST(CAST(:attempt AS uuid) AS text) "
                    "AND COALESCE(j.payload->>'_cancel_requested_v1','false')<>'true' "
                    "FOR UPDATE OF t,j FOR SHARE OF c"
                ),
                {
                    "task": UUID(payload[HARNESS_KEY]),
                    "job": UUID(request.job_id),
                    "owner": UUID(str(request.user_id)),
                    "thread": UUID(request.thread_id),
                    "attempt": UUID(payload[EXECUTION_KEY]),
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None or not exhausted(row["job_payload"]):
        raise JobStateUnavailable("Harness exhaustion ownership unavailable")
    return row


async def restore_exhausted_checkpoint(
    service: Any,
    *,
    request: Any,
    repository: Any,
    session: Any,
    state: Any,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not exhausted(payload):
        return None
    row = await _owned_task(session, request, payload)
    verified = await verify_accounting(session, row["job_payload"], request)
    if verified is None or verified.facts.attempt_id != payload[EXECUTION_KEY]:
        raise JobStateUnavailable("Harness exhaustion accounting unavailable")
    # Исчерпанный durable marker запрещает dispatch. Только неотправленные grants
    # можно снять; unknown/dispatched продолжают удерживать расход.
    await reconcile_tool_fees(session, row["task_id"])
    await session.execute(
        text(
            "UPDATE profile.harness_grant SET state='waived' "
            "WHERE task_id=:task AND state='allocated'"
        ),
        {"task": row["task_id"]},
    )
    grants = await grant_rows(session, row["task_id"])
    if all(grant["state"] == "waived" for grant in grants):
        verified_without_dispatch(row, payload, grants)
        journal = None
    else:
        journal = canonical_usage(payload[EXECUTION_KEY], payload.get(USAGE_JOURNAL_KEY), grants)
    current = await snapshot(session, row)
    result = await read_result(session, row, current)
    if result is None and current.state is None:
        # Контракт ещё не фиксировался. Не создаём фиктивные критерии или evidence.
        result = {
            "schema_version": 2,
            "status": "blocked",
            "verified": False,
            "blocker": "checkpoint_unavailable",
            "confirmed": [],
            "unchecked": ["contract"],
            "references": [],
            "rounds": 0,
            "repair_cycles": 0,
        }
    projection = TaskResultV2.model_validate(result)
    if projection.status != "blocked" or projection.blocker in {
        "cost_unknown",
        "operation_unknown",
    }:
        raise JobStateUnavailable("Harness exhaustion reconciliation required")
    if journal is not None:
        await stage_usage_journal(
            repository,
            session,
            job_id=UUID(request.job_id),
            owner_id=UUID(str(request.user_id)),
            thread_id=request.thread_id,
            payload=journal.payload(),
        )
        payload[USAGE_JOURNAL_KEY] = journal.payload()
    state.execution_attempt_id = payload[EXECUTION_KEY]
    state.harness_task_id = str(row["task_id"])
    state.harness_epoch = row["fencing_epoch"]
    state.usage_journal = journal
    state.usage_checkpointed = True
    state.reservation_id = verified.facts.reservation_id
    state.reserved_estimate = verified.facts.reserved_estimate
    result = exhausted_result(journal, projection, request.selected_model)
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
    if job is None:
        raise JobStateUnavailable("Harness exhaustion checkpoint unavailable")
    return job["payload"].get("_prepared_turn_v1")


def exhausted_result(
    journal: UsageJournal | None, projection: TaskResultV2, selected_model: str | None
) -> dict[str, Any]:
    receipts = journal.receipts if journal else ()
    prompt = sum(receipt.prompt for receipt in receipts)
    completion = sum(receipt.completion for receipt in receipts)
    reply = "Не удалось восстановить связь с исполнителем. " + (
        "Подтверждённые изменения сохранены."
        if projection.confirmed
        else "Проверенный результат не получен."
    )
    return {
        "reply": reply,
        "resolved_model": selected_model or (receipts[-1].model if receipts else None),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "per_call_usage": [receipt.payload() for receipt in receipts],
        "tool_summary": {},
        "metadata": {
            "execution_status": "partial",
            "task_result": projection.model_dump(mode="json"),
        },
        "reply_parts_count": 0,
        "reply_chars_count": len(reply),
    }
