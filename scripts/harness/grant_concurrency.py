"""Проверка денежных гонок на отдельной PostgreSQL-БД, без вызовов провайдеров."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from scripts.harness import runtime as fixture
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import CallReceipt, Exchange, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload

STAGE = "source_parity"


def tariff():
    return FrozenPricing(
        entries=[],
        classes=[],
        default={"model": "default", "incoming": "1", "outgoing": "1"},
        credit_unit="0.01",
        margin="1",
        complexity="1",
        minimum=10,
        minimum_margin="1",
        surcharges={},
    )


def call(*, prompt=600, completion=0):
    return PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=prompt,
        completion=completion,
        request_digest=digest_payload({"prompt": prompt, "completion": completion}),
    )


async def attempt(repo, owner, request):
    try:
        return await repo.exchange(owner, request)
    except HarnessFailure as error:
        return error.code


async def current(repo, owner):
    return (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]


async def grant_race(repo, owner):
    global STAGE
    STAGE = "parallel_grants"
    calls = [call(), call()]
    results = await asyncio.gather(
        *(attempt(repo, owner, Exchange(opcode="grant", call=item)) for item in calls)
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count("budget_exhausted") == 1
    winner = calls[next(i for i, result in enumerate(results) if isinstance(result, dict))]
    before = await current(repo, owner)
    assert before["spent_credits"] == 0 and before["held_credits"] == 60

    STAGE = "replayed_grant"
    replay = await asyncio.gather(
        *(repo.exchange(owner, Exchange(opcode="grant", call=winner)) for _ in range(4))
    )
    assert all(result["operation"]["status"] == "allocated" for result in replay)
    assert await current(repo, owner) == before
    changed = winner.model_copy(update={"prompt": 601})
    assert (
        await attempt(repo, owner, Exchange(opcode="grant", call=changed)) == "operation_conflict"
    )

    STAGE = "parallel_dispatch"
    results = await asyncio.gather(
        *(
            repo.exchange(owner, Exchange(opcode="dispatch", operation_id=winner.operation_id))
            for _ in range(4)
        )
    )
    assert sum(result["operation"]["dispatch_allowed"] for result in results) == 1
    return winner


async def receipt_race(repo, owner, winner):
    global STAGE
    STAGE = "parallel_receipts"
    receipt = CallReceipt(
        operation_id=winner.operation_id,
        status="succeeded",
        prompt=1,
        message={"role": "assistant", "content": "PRIVATE_RESULT"},
    )
    results = await asyncio.gather(
        *(repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt)) for _ in range(4))
    )
    assert all(result["operation"]["status"] == "succeeded" for result in results)
    state = await current(repo, owner)
    assert state["spent_credits"] == 10 and state["held_credits"] == 0
    assert len(state["usage"]) == 1
    changed = receipt.model_copy(update={"prompt": 2})
    assert (
        await attempt(repo, owner, Exchange(opcode="call_receipt", receipt=changed))
        == "operation_unknown"
    )
    assert await current(repo, owner) == state

    STAGE = "cumulative_minimum"
    second = call(prompt=1)
    await repo.exchange(owner, Exchange(opcode="grant", call=second))
    pending = await current(repo, owner)
    assert pending["spent_credits"] == 10 and pending["held_credits"] == 0
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=second.operation_id))
    await repo.exchange(
        owner,
        Exchange(
            opcode="call_receipt",
            receipt=receipt.model_copy(update={"operation_id": second.operation_id}),
        ),
    )
    state = await current(repo, owner)
    assert state["spent_credits"] == 10 and len(state["usage"]) == 2


async def unknown_race(repo, owner, factory):
    global STAGE
    STAGE = "unknown_cost_blocks_dispatch"
    uncertain, waiting, finishing = call(prompt=500), call(prompt=1), call(prompt=1)
    for item in (uncertain, waiting, finishing):
        await repo.exchange(owner, Exchange(opcode="grant", call=item))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=finishing.operation_id))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=uncertain.operation_id))
    receipt = CallReceipt(operation_id=uncertain.operation_id, status="unknown")
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
    requests = [
        Exchange(opcode="dispatch", operation_id=waiting.operation_id),
        Exchange(opcode="grant", call=call(prompt=1)),
    ]
    assert await asyncio.gather(*(attempt(repo, owner, item) for item in requests)) == [
        "cost_unknown",
        "cost_unknown",
    ]
    before = await current(repo, owner)
    assert before["held_credits"] > 0 and len(before["usage"]) == 2
    replay = await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
    assert replay["operation"]["status"] == "unknown"
    assert await current(repo, owner) == before

    STAGE = "dispatched_receipt_after_stop"
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_cancel_requested_v1',true) WHERE id=:job"
            ),
            {"job": UUID(owner.job_id)},
        )
        await db.commit()
    state = await current(repo, owner)
    assert state["stopped"] is True
    assert state["held_credits"] == before["held_credits"]
    denied = await attempt(
        repo, owner, Exchange(opcode="dispatch", operation_id=waiting.operation_id)
    )
    assert denied == "cancelled"
    completed = CallReceipt(
        operation_id=finishing.operation_id,
        status="succeeded",
        prompt=1,
        message={"role": "assistant", "content": "PRIVATE_LATE_RESULT"},
    )
    late = await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=completed))
    assert late["operation"]["status"] == "succeeded"
    after = await current(repo, owner)
    assert after["held_credits"] > 0 and len(after["usage"]) == 3
    assert (await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt)))[
        "operation"
    ]["status"] == "unknown"
    assert (await repo.exchange(owner, Exchange(opcode="result")))["result"][
        "status"
    ] == "cancelled"


async def exercise(engine):
    owner, admission = await fixture.seed(engine)
    factory = async_sessionmaker(engine, class_=fixture.ProbeSession, expire_on_commit=False)
    repo = HarnessRuntimeRepository(SimpleNamespace(get_session_context=factory))
    await repo.admit(owner, admission, tariff())
    await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "analysis",
                "criteria": [{"criterion_id": "read", "kind": "read", "target": "README.md"}],
            },
        ),
    )
    winner = await grant_race(repo, owner)
    await receipt_race(repo, owner, winner)
    await unknown_race(repo, owner, factory)
    async with factory() as db:
        count = await db.scalar(text("SELECT count(*) FROM profile.harness_grant"))
        assert count == 5
    return [
        "parallel_grants_share_budget",
        "grant_replay_and_conflict",
        "dispatch_once",
        "receipt_replay_and_conflict",
        "cumulative_minimum_once",
        "unknown_cost_blocks_allocated_dispatch",
        "stop_keeps_unknown_cost",
        "late_receipt_after_stop",
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
    async with fixture.disposable() as engine:
        async with asyncio.timeout(40):
            await zero_budget(engine)
            cases.append("local_zero_budget_no_paid_dispatch")
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


async def zero_budget(engine):
    global STAGE
    STAGE = "local_zero_budget"
    model = "qwen2.5-1.5b-instruct"
    owner, admission = await fixture.seed(engine, credit_limit=0, pricing_model=model)
    factory = async_sessionmaker(engine, class_=fixture.ProbeSession, expire_on_commit=False)
    repo = HarnessRuntimeRepository(SimpleNamespace(get_session_context=factory))
    await repo.admit(owner, admission, tariff())
    await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "analysis",
                "criteria": [{"criterion_id": "read", "kind": "read", "target": "README.md"}],
            },
        ),
    )
    local = call().model_copy(update={"provider": "local", "model": model})
    await repo.exchange(owner, Exchange(opcode="grant", call=local))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=local.operation_id))
    receipt = CallReceipt(
        operation_id=local.operation_id,
        status="succeeded",
        prompt=100,
        message={"role": "assistant", "content": "Проверочный ответ"},
    )
    for _ in range(2):
        await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
    snapshot = await current(repo, owner)
    assert snapshot["spent_credits"] == snapshot["held_credits"] == 0
    assert len(snapshot["usage"]) == 1
    assert await attempt(repo, owner, Exchange(opcode="grant", call=call())) == "budget_exhausted"
    async with factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM profile.harness_grant")) == 1
        assert await db.scalar(text("SELECT tokens_reserved FROM profile.token_reservations")) == 0


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
