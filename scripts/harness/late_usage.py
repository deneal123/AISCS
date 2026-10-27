"""Unknown → точный receipt в настоящем PostgreSQL; провайдер не вызывается."""

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
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import CallReceipt, Exchange, HarnessFailure, PaidCall

STAGE = "source_parity"


async def exercise(engine):
    global STAGE
    owner, admission = await fixture.seed(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
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
    await repo.admit(owner, admission, tariff)
    await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "change",
                "criteria": [{"criterion_id": "script", "kind": "file", "target": "a.py"}],
            },
        ),
    )
    call = PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=600,
        completion=20,
        kind="chat",
        request_digest="a" * 64,
    )
    await repo.exchange(owner, Exchange(opcode="grant", call=call))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=call.operation_id))
    STAGE = "unknown_cost_retained"
    await repo.exchange(
        owner,
        Exchange(
            opcode="call_receipt",
            receipt=CallReceipt(
                operation_id=call.operation_id,
                status="unknown",
            ),
        ),
    )
    before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert before["spent_credits"] == 0 and before["held_credits"] == 62 and not before["usage"]
    STAGE = "stop_and_expired_hold"
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_cancel_requested_v1',true) WHERE id=:job"
            ),
            {"job": UUID(owner.job_id)},
        )
        await db.execute(
            text("UPDATE profile.token_reservations SET expires_at=now()-interval '1 hour'")
        )
        await db.commit()
    assert await BillingRepository(connector).cleanup_expired_reservations() == 0
    STAGE = "late_exact_usage_after_stop"
    from service.services.chat.application.harness_capability import settings

    os.environ["HARNESS__IDE_ENABLED"] = "false"
    settings.cache_clear()
    receipt = CallReceipt(
        operation_id=call.operation_id,
        status="succeeded",
        prompt=12,
        completion=3,
        message={"role": "assistant", "content": "PRIVATE_CONFIRMED_RESPONSE"},
    )
    try:
        await repo.exchange(
            owner.model_copy(update={"epoch": owner.epoch + 1}),
            Exchange(opcode="call_receipt", receipt=receipt),
        )
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("foreign_attempt_resolved_cost")
    results = await asyncio.gather(
        *(repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt)) for _ in range(4))
    )
    assert all(result["operation"]["status"] == "succeeded" for result in results)
    after = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert after["stopped"] and after["held_credits"] == 0
    assert after["spent_credits"] == 2 and len(after["usage"]) == 1
    assert after["usage"][0]["receipt_id"] == call.operation_id
    assert await BillingRepository(connector).cleanup_expired_reservations() == 0
    STAGE = "no_new_execution_or_result"
    try:
        await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=call.operation_id))
    except HarnessFailure as error:
        assert error.code == "cancelled"
    else:
        raise AssertionError("late_receipt_revived_dispatch")
    result = (await repo.exchange(owner, Exchange(opcode="result")))["result"]
    assert result["status"] == "cancelled" and not result["verified"]
    assert result["confirmed"] == []
    try:
        await repo.exchange(
            owner,
            Exchange(opcode="call_receipt", receipt=receipt.model_copy(update={"prompt": 13})),
        )
    except HarnessFailure as error:
        assert error.code == "operation_unknown"
    else:
        raise AssertionError("settled_receipt_replaced")
    assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == after
    return [
        "unknown_hold_survives_stop_ttl",
        "exact_usage_resolves_same_operation",
        "concurrent_receipts_count_once",
        "late_usage_cannot_revive_execution",
        "changed_receipt_rejected",
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
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
