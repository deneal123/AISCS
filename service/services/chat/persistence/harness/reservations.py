"""Retain financial obligations, not execution permission, in the existing hold."""

from uuid import UUID

from sqlalchemy import text

from service.shared.harness_protocol import HarnessFailure


async def require_reconciled_cost(db, task_id, *, except_operation_id=None):
    """A human answer cannot turn a lost provider ACK into a fresh paid attempt."""
    uncertain = await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_grant "
            "WHERE task_id=:task AND state IN ('dispatched','unknown') "
            + (
                "AND NOT(state='dispatched' AND operation_id=:except_op))"
                if except_operation_id
                else ")"
            )
        ),
        {
            "task": UUID(str(task_id)),
            **({"except_op": except_operation_id} if except_operation_id else {}),
        },
    )
    if uncertain:
        raise HarnessFailure("cost_unknown")


async def retain(db, *, task_id, user_id, reservation_id, credits):
    """Claim only an active owned hold, atomically with task admission/handoff.

    Billing cleanup competes for this same reservation row. A refunded/expired
    admission cannot be revived; once retained, TTL cannot erase the obligation.
    """
    retained = await db.scalar(
        text(
            "UPDATE profile.token_reservations SET harness_task_id=:task "
            "WHERE reservation_id=:reservation AND user_id=:owner AND status='reserved' "
            "AND expires_at>now() AND tokens_reserved>=:credits "
            "AND (harness_task_id IS NULL OR harness_task_id=:task) RETURNING reservation_id"
        ),
        {
            "task": UUID(str(task_id)),
            "owner": UUID(str(user_id)),
            "reservation": UUID(str(reservation_id)),
            "credits": credits,
        },
    )
    if retained != UUID(str(reservation_id)):
        raise HarnessFailure("budget_unavailable")
