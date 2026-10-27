"""Question-child handoff with an already confirmed hold; no new permission or budget."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.application.harness_capability import HarnessOwner
from service.services.chat.persistence.harness.admission.workspace_scope import bind_workspace
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.services.chat.persistence.harness.reservations import require_reconciled_cost, retain
from service.services.chat.persistence.harness.state import owned_row
from service.shared.harness_protocol import HarnessFailure


async def rebind_harness(connector, owner, *, reservation_id, parent_id, workspace_id=None):
    try:
        async with connector.get_session_context() as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT t.*,j.payload AS job_payload FROM profile.harness_task t "
                            "JOIN profile.user_launch j ON j.id=t.active_job_id "
                            "WHERE t.task_id=:task_id AND t.user_id=:user_id "
                            "AND t.thread_id=:thread_id FOR UPDATE OF t"
                        ),
                        owner.params(),
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise HarnessFailure("harness_fenced")
            if row["active_job_id"] == UUID(owner.job_id):
                await owned_row(db, owner)
                await bind_workspace(db, row, owner, workspace_id)
                await db.commit()
                return owner
            if parent_id is None or row["active_job_id"] != parent_id:
                raise HarnessFailure("harness_fenced")
            admission = await bind_workspace(db, row, owner, workspace_id)
            await reconcile_tool_fees(db, row["task_id"])
            await require_reconciled_cost(db, row["task_id"])
            valid = await db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM profile.human_question q "
                    "JOIN profile.user_launch j ON j.id=q.resume_job_id "
                    "JOIN profile.token_reservations r ON r.reservation_id=:reservation "
                    "AND r.user_id=j.user_id AND r.status='reserved' AND r.expires_at>now() "
                    "AND r.tokens_reserved>=:remaining "
                    "WHERE q.source_job_id=:parent AND q.resume_job_id=:job_id "
                    "AND q.user_id=:user_id AND q.thread_id=:thread_id AND q.state='accepted' "
                    "AND j.status='PROCESSING' AND j.payload->>'_execution_attempt_v1'="
                    "CAST(CAST(:attempt_id AS uuid) AS text) "
                    "AND COALESCE(j.payload::jsonb->'_cancel_requested_v1',"
                    "'false'::jsonb)<>'true'::jsonb)"
                ),
                {
                    **owner.params(),
                    "parent": parent_id,
                    "reservation": UUID(reservation_id),
                    "remaining": admission.credit_limit - row["settled_credits"],
                },
            )
            if valid is not True:
                raise HarnessFailure("harness_fenced")
            await retain(
                db,
                task_id=owner.task_id,
                user_id=owner.user_id,
                reservation_id=reservation_id,
                credits=admission.credit_limit - row["settled_credits"],
            )
            raw = admission.model_dump(mode="json")
            raw["reservation_id"] = reservation_id
            await db.execute(
                text(
                    "UPDATE profile.harness_task SET active_job_id=:job_id,"
                    "execution_attempt_id=:attempt_id,"
                    "fencing_epoch=fencing_epoch+1,admission=CAST(:admission AS jsonb) "
                    "WHERE task_id=:task_id AND fencing_epoch=:epoch"
                ),
                {**owner.params(), "epoch": row["fencing_epoch"], "admission": json.dumps(raw)},
            )
            await db.execute(
                text(
                    "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
                    "'{_harness_task_v1}',to_jsonb(CAST(:task AS text)),true) WHERE id=:job"
                ),
                {"task": owner.task_id, "job": UUID(owner.job_id)},
            )
            raw_owner = owner.model_dump()
            raw_owner["epoch"] = row["fencing_epoch"] + 1
            bound = HarnessOwner.model_validate(raw_owner)
            await owned_row(db, bound)
            await db.commit()
            return bound
    except HarnessFailure:
        raise
    except Exception:
        raise HarnessFailure() from None
