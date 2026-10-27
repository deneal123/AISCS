"""Fault injection at settlement boundaries; no database/provider stand access."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.harness import accounting


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["plan_commit", "charge_commit", "settlement_commit"])
async def test_unknown_ack_reuses_same_plan_and_charge_identity(monkeypatch, lost):
    job_id, task_id, reservation_id, user_id = (str(uuid4()) for _ in range(4))
    plan = {
        "task_id": task_id,
        "job_id": job_id,
        "reservation_id": reservation_id,
        "credits": 30,
        "cumulative": 30,
        "tokens": 100,
        "raw_cost_rub": "0.3",
    }
    lost_once, charges, billed = set(), [], set()

    class Connector:
        @asynccontextmanager
        async def get_session_context(self):
            db = SimpleNamespace(phase="settlement_commit", execute=AsyncMock())

            async def commit():
                if db.phase == lost and db.phase not in lost_once:
                    lost_once.add(db.phase)
                    raise ConnectionError("PRIVATE_COMMIT_ACK")

            db.commit = commit
            yield db

    class Billing:
        def __init__(self, *args):
            pass

        async def charge(self, owner, **kwargs):
            charges.append((owner, kwargs))
            key = kwargs["idempotency_key"]
            if key in billed:
                return {"idempotent": True, "from_subscription": 0, "from_topup": 0}
            billed.add(key)
            if lost == "charge_commit" and lost not in lost_once:
                lost_once.add(lost)
                raise ConnectionError("PRIVATE_CHARGE_ACK")
            return {"from_subscription": 30, "from_topup": 0}

    async def prepare(db, *_):
        db.phase = "plan_commit"
        return plan

    monkeypatch.setattr(accounting, "_plan", prepare)
    monkeypatch.setattr(accounting, "BillingService", Billing)
    connector, config = Connector(), SimpleNamespace(billing=object())
    with pytest.raises(JobStateUnavailable) as error:
        await accounting.charge_harness(connector, config, user_id=user_id, job_id=job_id)
    assert "PRIVATE" not in str(error.value)
    if lost == "plan_commit":
        assert not charges, "an unacknowledged plan cannot initiate a charge"
    result = await accounting.charge_harness(connector, config, user_id=user_id, job_id=job_id)
    assert result == (30 if lost == "plan_commit" else 0)
    assert billed == {job_id}
    assert len(charges) == (1 if lost == "plan_commit" else 2)
    assert all(
        owner == user_id and body["reservation_id"] == reservation_id for owner, body in charges
    )
    assert all(body["idempotency_key"] == job_id and body["credits"] == 30 for _, body in charges)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["unknown", "dispatched"])
async def test_unresolved_cost_never_reaches_charge_or_floor_fallback(monkeypatch, state):
    monkeypatch.setattr(accounting, "reconcile_tool_fees", AsyncMock(return_value=0))
    task, job, user = uuid4(), uuid4(), uuid4()
    row = {
        "task_id": task,
        "job_payload": {"_accepted_turn_v1": {}},
    }
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: row))
        )
    )
    monkeypatch.setattr(accounting, "grant_rows", AsyncMock(return_value=[{"state": state}]))
    with pytest.raises(JobStateUnavailable, match="cost reconciliation required"):
        await accounting._plan(db, str(user), str(job))
    assert db.execute.await_count == 2  # owned row and waiver of never-dispatched grants
    assert all("token_reservations" not in str(args[0][0]) for args in db.execute.call_args_list)
