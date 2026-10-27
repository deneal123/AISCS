"""Owned reservation evidence is separate from authority to charge or release."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.billing.execution_accounting import (
    ExecutionAccounting,
)
from service.services.chat.infrastructure.chat_worker.billing.reservation.recovery import (
    ReservationState,
    require_reservation_projection,
    verify_accounting,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.run_contracts import WorkerRunRequest
from service.services.jobs.persistence.transitions import ACCOUNTING_KEY, EXECUTION_KEY


def fixture():
    request = WorkerRunRequest(str(uuid4()), str(uuid4()), "PRIVATE_REQUEST", str(uuid4()))
    facts = ExecutionAccounting(str(uuid4()), str(uuid4()), 70)
    payload = {
        ACCOUNTING_KEY: facts.payload(),
        EXECUTION_KEY: facts.attempt_id,
        "thread_id": request.thread_id,
    }
    row = {"tokens_reserved": 70, "status": "reserved", "expired": False, "charged": False}
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
    session = AsyncMock()
    session.execute.return_value = result
    return request, facts, payload, row, session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expired,charged,expected",
    [
        ("reserved", False, False, ReservationState.ACTIVE),
        ("reserved", True, False, ReservationState.EXPIRED),
        ("expired", True, False, ReservationState.EXPIRED),
        ("refunded", True, False, ReservationState.RELEASED),
        ("committed", False, True, ReservationState.COMMITTED),
    ],
)
async def test_owned_record_is_read_only(status, expired, charged, expected):
    request, facts, payload, row, session = fixture()
    row.update(status=status, expired=expired, charged=charged)
    verified = await verify_accounting(session, payload, request)
    assert verified.facts == facts and verified.reservation_state == expected
    query, params = session.execute.await_args.args
    assert "user_id=:owner" in str(query) and "FOR UPDATE" not in str(query)
    assert str(params["owner"]) == request.user_id
    assert params["job"] == request.job_id
    session.commit.assert_not_awaited()
    require_reservation_projection(
        verified, {"reservation_id": facts.reservation_id, "reserved_estimate": 70}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "amount",
        "boolean",
        "status",
        "committed",
        "attempt",
        "thread",
        "protocol",
        "outage",
    ],
)
async def test_malformed_or_foreign_evidence_never_authorizes_recovery(fault):
    request, _, payload, row, session = fixture()
    if fault == "missing":
        session.execute.return_value = SimpleNamespace(
            mappings=lambda: SimpleNamespace(first=lambda: None)
        )
    elif fault == "amount":
        row["tokens_reserved"] = 71
    elif fault == "boolean":
        row["tokens_reserved"] = True
    elif fault == "status":
        row["status"] = "PRIVATE_MARKER"
    elif fault == "committed":
        row["status"] = "committed"
    elif fault == "attempt":
        payload[EXECUTION_KEY] = str(uuid4())
    elif fault == "thread":
        payload["thread_id"] = str(uuid4())
    elif fault == "protocol":
        row["expired"] = "PRIVATE_MARKER"
    else:
        session.execute.side_effect = RuntimeError("PRIVATE_MARKER")
    with pytest.raises(JobStateUnavailable) as error:
        await verify_accounting(session, payload, request)
    assert str(error.value) == "Reservation recovery unavailable"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_nullable_hold_and_legacy_do_not_query_billing():
    request, facts, payload, _, session = fixture()
    payload[ACCOUNTING_KEY] = ExecutionAccounting(facts.attempt_id, None, 0).payload()
    assert (
        await verify_accounting(session, payload, request)
    ).reservation_state == ReservationState.NONE
    assert await verify_accounting(session, {}, request) is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["reservation_id", "reserved_estimate"])
async def test_accepted_projection_cannot_select_another_reservation(field):
    request, facts, payload, _, session = fixture()
    verified = await verify_accounting(session, payload, request)
    private = {"reservation_id": facts.reservation_id, "reserved_estimate": 70}
    private[field] = str(uuid4()) if field == "reservation_id" else 71
    with pytest.raises(JobStateUnavailable):
        require_reservation_projection(verified, private)
