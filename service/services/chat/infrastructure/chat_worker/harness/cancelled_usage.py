"""Восстановление usage отменённого harness только из подтверждённых grant receipts."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    UsageJournal,
    stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.cancellation import CancelledByUser
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness.zero_usage import (
    verified_without_dispatch,
)
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.services.chat.persistence.harness.state import grant_rows
from service.services.jobs.persistence.transitions import (
    EXECUTION_KEY,
    HARNESS_KEY,
    USAGE_JOURNAL_KEY,
)


def canonical_usage(attempt_id, previous, grants):
    if any(item["state"] in {"dispatched", "unknown"} for item in grants):
        raise JobStateUnavailable("Cancelled harness cost unknown")
    receipts = [
        {
            "receipt_id": str(item["operation_id"]),
            "provider": item["request"]["provider"],
            "model": item["request"]["model"],
            "kind": item["request"]["kind"],
            "prompt": item["receipt"]["prompt"],
            "completion": item["receipt"]["completion"],
            "estimated": item["receipt"]["estimated"],
        }
        for item in grants
        if item["state"] == "succeeded" and not item["request"].get("billing_tool")
    ]
    if not receipts:
        raise JobStateUnavailable("Cancelled harness usage unavailable")
    old = UsageJournal.decode(previous) if previous is not None else None
    journal = UsageJournal.decode(
        {
            "schema_version": 1,
            "attempt_id": attempt_id,
            "revision": old.revision + 1 if old else 1,
            "receipts": receipts,
        }
    )
    if old and journal.receipts == old.receipts and old.attempt_id == attempt_id:
        return old
    if old and not journal.extends(old):
        raise JobStateUnavailable("Cancelled harness usage mismatch")
    return journal


async def restore_cancelled_usage(repository, session, request, payload):
    if payload.get("_cancel_requested_v1") is not True or HARNESS_KEY not in payload:
        return
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.task_id,t.admission,t.usage_history,t.settled_credits "
                    "FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id AND j.user_id=t.user_id "
                    "WHERE t.task_id=:task AND t.active_job_id=:job AND t.user_id=:owner "
                    "AND t.thread_id=:thread AND t.execution_attempt_id=:attempt "
                    "AND j.type='CHAT' AND j.status='PROCESSING' "
                    "AND j.payload->>'thread_id'=CAST(CAST(:thread AS uuid) AS text) "
                    "AND j.payload->>'_execution_attempt_v1'=CAST(CAST(:attempt AS uuid) AS text) "
                    "AND j.payload->>'_cancel_requested_v1'='true' FOR UPDATE OF t,j"
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
    if row is None:
        raise JobStateUnavailable("Cancelled harness ownership unavailable")
    # Stop запрещает повтор эффекта, но не сверку уже сохранённого receipt.
    # Потерянный ACK локальной надбавки не должен блокировать известный расход.
    await reconcile_tool_fees(session, row["task_id"])
    # Stop запрещает dispatch. Только ещё не отправленные allocations можно снять.
    await session.execute(
        text(
            "UPDATE profile.harness_grant SET state='waived' "
            "WHERE task_id=:task AND state='allocated'"
        ),
        {"task": row["task_id"]},
    )
    grants = await grant_rows(session, row["task_id"])
    if all(grant["state"] == "waived" for grant in grants):
        return verified_without_dispatch(row, payload, grants)
    journal = canonical_usage(
        payload[EXECUTION_KEY],
        payload.get(USAGE_JOURNAL_KEY),
        grants,
    )
    await stage_usage_journal(
        repository,
        session,
        job_id=UUID(request.job_id),
        owner_id=UUID(str(request.user_id)),
        thread_id=request.thread_id,
        payload=journal.payload(),
    )
    payload[USAGE_JOURNAL_KEY] = journal.payload()


async def settle_harness_cancellation(execution, repository, request, state):
    try:
        return await execution
    except CancelledByUser:
        from service.services.chat.infrastructure.chat_worker.billing.cancelled import (
            cancelled_result,
        )

        async with repository.connector.get_session_context() as db:
            job = await repository.lock_prepared_turn(
                UUID(request.job_id), UUID(str(request.user_id)), session=db
            )
            if (
                job is None
                or job["status"] != "PROCESSING"
                or job["payload"].get(EXECUTION_KEY) != state.execution_attempt_id
                or job["payload"].get("_cancel_requested_v1") is not True
            ):
                raise JobStateUnavailable("Cancelled harness ownership unavailable") from None
            payload = job["payload"]
            zero = await restore_cancelled_usage(repository, db, request, payload)
            journal = None if zero else UsageJournal.decode(payload[USAGE_JOURNAL_KEY])
            await db.commit()
        state.usage_journal = journal
        state.cancelled_without_dispatch = zero is True
        state.usage_checkpointed = True
        state.cancelled_execution = True
        return cancelled_result(state, request.selected_model)
