"""Настоящий PostgreSQL: bounded retry journal, fencing и потерянный commit ACK."""

import asyncio
import hashlib
import json
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from scripts.harness import runtime as fixture
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.infrastructure.chat_worker.execution.lease import claim_execution_session
from service.services.chat.infrastructure.chat_worker.harness.recovery import recover_harness
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)
from service.services.chat.persistence.harness.retry import RETRY_KEY, HarnessRetryRepository
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import CallReceipt, Exchange, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload

STAGE = "source_parity"


class LostCommitAck(fixture.ProbeSession):
    async def commit(self):
        await super().commit()
        raise ConnectionError("PRIVATE_COMMIT_ACK")


def parameters(owner):
    return dict(
        task_id=owner.task_id,
        job_id=owner.job_id,
        user_id=owner.user_id,
        thread_id=owner.thread_id,
        attempt_id=owner.attempt_id,
        epoch=owner.epoch,
    )


async def prepare_fixture(engine):
    global STAGE
    STAGE = "fixture_seed"
    owner, admission = await fixture.seed(engine)
    factory = async_sessionmaker(engine, class_=fixture.ProbeSession, expire_on_commit=False)
    connector = SimpleNamespace(get_session_context=factory)
    repo = HarnessRuntimeRepository(connector)
    tariff = FrozenPricing(
        entries=[],
        classes=[],
        default={"model": "default", "incoming": "1", "outgoing": "1"},
        credit_unit="0.01",
        margin="1",
        complexity="1",
        minimum=0,
        minimum_margin="1",
        surcharges={},
    )
    STAGE = "admission"
    await repo.admit(owner, admission, tariff)
    STAGE = "seal"
    await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "analysis",
                "criteria": [{"criterion_id": "read", "kind": "read", "target": "a.py"}],
            },
        ),
    )
    call = PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=100,
        completion=0,
        request_digest=digest_payload({"probe": "retry"}),
    )
    STAGE = "initial_unknown_grant"
    await repo.exchange(owner, Exchange(opcode="grant", call=call))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=call.operation_id))
    await repo.exchange(
        owner,
        Exchange(
            opcode="call_receipt",
            receipt=CallReceipt(operation_id=call.operation_id, status="unknown"),
        ),
    )
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_execution_accounting_v1',jsonb_build_object("
                "'attempt_id',CAST(:attempt AS text),'reservation_id',CAST(:reservation AS text),"
                "'reserved_estimate',100)) WHERE id=:job"
            ),
            {
                "job": UUID(owner.job_id),
                "attempt": owner.attempt_id,
                "reservation": admission.reservation_id,
            },
        )
        await db.commit()
    return owner, call, connector, factory, repo


async def advance_owner(connector, factory, owner):
    request = WorkerRunRequest(
        job_id=owner.job_id, thread_id=owner.thread_id, text="PRIVATE_PROBE", user_id=owner.user_id
    )
    state = MutableRunState()
    async with claim_execution_session(connector, owner.task_id) as lease:
        assert lease is not None
        async with factory() as db:
            assert await recover_harness(db, request, state)
    return owner.model_copy(
        update={"attempt_id": state.execution_attempt_id, "epoch": state.harness_epoch}
    )


async def exercise(engine):
    global STAGE
    owner, call, connector, factory, repo = await prepare_fixture(engine)
    retry = HarnessRetryRepository(connector)
    before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    STAGE = "commit_ack_loss"
    losing = async_sessionmaker(engine, class_=LostCommitAck, expire_on_commit=False)
    try:
        await HarnessRetryRepository(SimpleNamespace(get_session_context=losing)).prepare(
            **parameters(owner)
        )
    except HarnessFailure as error:
        assert error.code == "checkpoint_unavailable"
    else:
        raise AssertionError("lost_ack_authorized_dispatch")
    STAGE = "parallel_reconciliation"
    decisions = await asyncio.gather(*(retry.prepare(**parameters(owner)) for _ in range(4)))
    assert all(
        item[0] == {"attempt_id": owner.attempt_id, "count": 1, "state": "pending"}
        for item in decisions
    )
    STAGE = "old_dispatch_fenced"
    try:
        await repo.exchange(
            owner,
            Exchange(opcode="grant", call=call.model_copy(update={"operation_id": str(uuid4())})),
        )
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("old_attempt_dispatched")
    STAGE = "owner_transfer_counter"
    original = owner
    for expected in (2, 3):
        owner = await advance_owner(connector, factory, owner)
        decision, result = await retry.prepare(**parameters(owner))
        assert decision["count"] == expected and decision["state"] == "pending" and result is None
    try:
        await retry.prepare(**parameters(original))
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("fenced_attempt_recovered")
    owner = await advance_owner(connector, factory, owner)
    decision, result = await retry.prepare(**parameters(owner))
    assert decision["count"] == 3 and decision["state"] == "blocked"
    assert result["status"] == "blocked" and result["blocker"] == "cost_unknown"
    assert result["rounds"] == 0 and not result["verified"]
    after = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert after["held_credits"] == before["held_credits"] > 0
    assert after["admission"] == before["admission"]
    STAGE = "stop_blocks_delivery"
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_cancel_requested_v1',true) WHERE id=:job"
            ),
            {"job": UUID(owner.job_id)},
        )
        await db.commit()
    try:
        await retry.prepare(**parameters(owner))
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("stopped_delivery_admitted")
    STAGE = "late_receipt_allowed"
    receipt = CallReceipt(
        operation_id=call.operation_id,
        status="succeeded",
        prompt=1,
        message={"role": "assistant", "content": "PRIVATE_RESULT"},
    )
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
    assert (await repo.exchange(owner, Exchange(opcode="result")))["result"][
        "status"
    ] == "cancelled"
    async with factory() as db:
        payload = await db.scalar(
            text("SELECT payload FROM profile.user_launch WHERE id=:job"),
            {"job": UUID(owner.job_id)},
        )
        assert payload[RETRY_KEY] == decision
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_operation")) == 0
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_grant")) == 1
    return [
        "committed_counter_ack_loss",
        "parallel_same_attempt_once",
        "pending_fences_old_dispatch",
        "fenced_attempt_rejected",
        "counters_across_recovery",
        "exhaustion_retains_unknown",
        "stop_blocks_delivery",
        "late_receipt_without_dispatch",
    ]


async def main():
    files = json.load(sys.stdin)["files"]
    assert all(
        hashlib.sha256(
            (Path(__file__).resolve().parents[1] / path.removeprefix("scripts/")).read_bytes()
            if path.startswith("scripts/")
            else Path(path).read_bytes()
        ).hexdigest()
        == digest
        for path, digest in files.items()
    )
    os.environ["HARNESS__IDE_ENABLED"] = "true"
    async with fixture.disposable() as engine:
        async with asyncio.timeout(40):
            cases = await exercise(engine)
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(
            json.dumps(
                {
                    "failed_stage": STAGE,
                    "error": type(error).__name__,
                    "frames": [
                        {"function": item.name, "line": item.lineno}
                        for item in traceback.extract_tb(error.__traceback__)[-4:]
                    ],
                }
            )
        )
        raise SystemExit(1) from None
