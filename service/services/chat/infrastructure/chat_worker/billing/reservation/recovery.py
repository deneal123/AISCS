"""Read-only owned reservation verification before recovery can settle usage."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
    ExecutionAccounting,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerRunRequest
from service.services.jobs.persistence.transitions import ACCOUNTING_KEY, EXECUTION_KEY


class ReservationState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    COMMITTED = "committed"
    RELEASED = "released"


@dataclass(frozen=True, slots=True)
class VerifiedAccounting:
    facts: ExecutionAccounting
    reservation_state: ReservationState


_OWNED_RESERVATION = text(
    "SELECT tokens_reserved,status,(expires_at<=now()) AS expired,"
    "EXISTS(SELECT 1 FROM profile.billing_events WHERE user_id=:owner "
    "AND event_type='usage' AND metadata->>'idempotency_key'=:job) AS charged "
    "FROM profile.token_reservations WHERE reservation_id=:reservation AND user_id=:owner"
)


async def verify_accounting(
    session: Any, payload: dict[str, Any], request: WorkerRunRequest
) -> VerifiedAccounting | None:
    """Never acquire a reservation row lock held across an independent charge.

    Expiry/release describe the hold, not whether recorded provider work happened.
    This function does not authorize a charge, release funds or replay a model.
    """
    if ACCOUNTING_KEY not in payload:
        return None  # Isolated legacy recovery retains its existing contract.
    try:
        facts = ExecutionAccounting.decode(payload[ACCOUNTING_KEY])
        if payload.get(EXECUTION_KEY) != facts.attempt_id:
            raise ValueError
        if payload.get("thread_id") != request.thread_id:
            raise ValueError
        owner = UUID(str(request.user_id))
        if facts.reservation_id is None:
            return VerifiedAccounting(facts, ReservationState.NONE)
        result = await session.execute(
            _OWNED_RESERVATION,
            {
                "reservation": UUID(facts.reservation_id),
                "owner": owner,
                "job": request.job_id,
            },
        )
        row = result.mappings().first()
        if row is None or type(row["tokens_reserved"]) is not int:
            raise ValueError
        if row["tokens_reserved"] != facts.reserved_estimate:
            raise ValueError
        if type(row["expired"]) is not bool or type(row["charged"]) is not bool:
            raise ValueError
        status = row["status"]
        if status == "reserved":
            state = ReservationState.EXPIRED if row["expired"] else ReservationState.ACTIVE
        elif status == "expired" and row["expired"]:
            state = ReservationState.EXPIRED
        elif status == "refunded":
            state = ReservationState.RELEASED
        elif status == "committed" and row["charged"]:
            state = ReservationState.COMMITTED
        else:
            raise ValueError
        return VerifiedAccounting(facts, state)
    except Exception:
        raise JobStateUnavailable("Reservation recovery unavailable") from None


def require_reservation_projection(
    verified: VerifiedAccounting | None, private: dict[str, Any]
) -> None:
    if verified is None:
        return
    if (
        private.get("reservation_id") != verified.facts.reservation_id
        or type(private.get("reserved_estimate")) is not int
        or private["reserved_estimate"] != verified.facts.reserved_estimate
    ):
        raise JobStateUnavailable("Reservation recovery unavailable")
