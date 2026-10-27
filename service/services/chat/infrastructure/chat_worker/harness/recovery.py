"""Fenced transfer under the existing task-level execution lease; never replay effects."""

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from service.services.chat.application.harness_capability import settings
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees


async def task_identity(connector, request):
    config = settings()
    resumed = getattr(request.question_resume, "harness_task_id", None)
    if not config.ide_enabled and not config.pdf_enabled and resumed is None:
        return request.job_id
    try:
        async with connector.get_session_context() as db:
            root = await db.scalar(
                text(
                    "SELECT task_id FROM profile.harness_task "
                    "WHERE user_id=:owner AND thread_id=:thread "
                    "AND (active_job_id=:job OR task_id=:root OR active_job_id IN "
                    "(SELECT source_job_id FROM profile.human_question WHERE resume_job_id=:job "
                    "AND user_id=:owner AND thread_id=:thread AND state='accepted')) "
                    "AND admission IS NOT NULL"
                ),
                {
                    "owner": UUID(str(request.user_id)),
                    "thread": UUID(request.thread_id),
                    "job": UUID(request.job_id),
                    "root": resumed,
                },
            )
        return str(root) if root else request.job_id
    except Exception:
        raise JobStateUnavailable("Harness ownership unavailable") from None


async def recover_harness(session, request, state):
    config = settings()
    parent = getattr(request.question_resume, "harness_task_id", None)
    if not config.ide_enabled and not config.pdf_enabled and parent is None:
        return False
    try:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT t.*,j.payload AS job_payload,j.status AS job_status "
                        "FROM profile.harness_task t "
                        "JOIN profile.user_launch j ON j.id=:job AND j.user_id=t.user_id "
                        "WHERE t.user_id=:owner AND t.thread_id=:thread AND admission IS NOT NULL "
                        "AND (t.active_job_id=:job OR t.task_id=:root) FOR UPDATE OF t,j"
                    ),
                    {
                        "owner": UUID(str(request.user_id)),
                        "thread": UUID(request.thread_id),
                        "job": UUID(request.job_id),
                        "root": parent,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return False
        state.harness_task_id = str(row["task_id"])
        state.harness_epoch = row["fencing_epoch"]
        state.harness_remaining = row["admission"]["credit_limit"] - row["settled_credits"]
        if row["active_job_id"] != UUID(request.job_id):
            if (
                request.question_resume is None
                or row["active_job_id"] != request.question_resume.source_job_id
            ):
                raise ValueError
            return (
                False  # First execution of the durable question child still uses the normal claim.
            )
        payload = dict(row["job_payload"])
        if (
            row["job_status"] != "PROCESSING"
            or payload.get("_cancel_requested_v1") is True
            or any(
                key in payload
                for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
            )
        ):
            raise ValueError
        if payload.get("_execution_attempt_v1") != str(row["execution_attempt_id"]):
            raise ValueError
        if (payload.get("_harness_transport_retry_v1") or {}).get("state") == "blocked":
            raise ValueError
        await reconcile_tool_fees(session, row["task_id"])
        attempt = str(uuid4())
        payload["_execution_attempt_v1"] = attempt
        accounting = dict(payload["_execution_accounting_v1"])
        accounting["attempt_id"] = attempt
        payload["_execution_accounting_v1"] = accounting
        journal = payload.get("_usage_journal_v1")
        history = list(row["usage_history"])
        if isinstance(journal, dict):
            if len(history) >= 32:
                raise ValueError
            history.append(journal)
            payload.pop("_usage_journal_v1")
        await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=CAST(:body AS jsonb),updated_at=now() "
                "WHERE id=:job"
            ),
            {"job": UUID(request.job_id), "body": json.dumps(payload)},
        )
        await session.execute(
            text(
                "UPDATE profile.harness_task SET execution_attempt_id=:attempt,"
                "fencing_epoch=fencing_epoch+1,usage_history=CAST(:history AS jsonb) "
                "WHERE task_id=:task"
            ),
            {"task": row["task_id"], "attempt": UUID(attempt), "history": json.dumps(history)},
        )
        await session.execute(
            text(
                "UPDATE profile.harness_grant SET state='unknown' "
                "WHERE task_id=:task AND state='dispatched'"
            ),
            {"task": row["task_id"]},
        )
        state.execution_attempt_id = attempt
        state.harness_epoch += 1
        state.reservation_id = accounting["reservation_id"]
        state.reserved_estimate = accounting["reserved_estimate"]
        state.harness_recovered = True
        await session.commit()
        return True
    except Exception:
        raise JobStateUnavailable("Harness recovery unavailable") from None


async def verify_harness_attempt(session, request, state):
    if not state.harness_task_id:
        return
    valid = await session.scalar(
        text(
            "SELECT t.task_id FROM profile.harness_task t JOIN profile.user_launch j "
            "ON j.id=t.active_job_id WHERE t.task_id=:task AND t.active_job_id=:job "
            "AND t.execution_attempt_id=:attempt AND t.fencing_epoch=:epoch "
            "AND j.status='PROCESSING' "
            "AND COALESCE(j.payload::jsonb->>'_cancel_requested_v1','false')="
            "CASE WHEN :cancelled THEN 'true' ELSE 'false' END "
            "FOR UPDATE OF t,j"
        ),
        {
            "task": UUID(state.harness_task_id),
            "job": UUID(request.job_id),
            "attempt": UUID(state.execution_attempt_id),
            "epoch": state.harness_epoch,
            "cancelled": getattr(state, "cancelled_execution", False) is True,
        },
    )
    if valid != UUID(state.harness_task_id):
        raise JobStateUnavailable("Harness execution fenced")
