"""Receipt terminal и continuation counter в одноразовой PG-БД, без model dispatch."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from scripts.harness import runtime as fixture
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import CallReceipt, Exchange, HarnessFailure, PaidCall
from service.shared.task_contract import digest_payload

STAGE = "source_parity"


def call_for(messages, step):
    body = {"model": "test-model", "messages": messages, "max_tokens": 20}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
    return PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=len(encoded.encode()) + 1024,
        completion=20,
        canonical_request=encoded,
        request_digest=digest_payload(body),
        continuation_step=step,
    )


async def exercise(engine):
    global STAGE
    owner, admission = await fixture.seed(engine)
    connector = SimpleNamespace(
        get_session_context=async_sessionmaker(engine, expire_on_commit=False)
    )
    repo = HarnessRuntimeRepository(connector)
    tariff = FrozenPricing(
        entries=[],
        classes=[],
        default={"model": "default", "incoming": "0.01", "outgoing": "0.01"},
        credit_unit="0.01",
        margin="1",
        complexity="1",
        minimum=0,
        minimum_margin="1",
        surcharges={},
    )
    await repo.admit(owner, admission, tariff)
    sealed = await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "analysis",
                "criteria": [
                    {"criterion_id": "read", "kind": "read", "target": "README.md"},
                ],
            },
        ),
    )
    conversation = [{"role": "user", "content": "Прочитай README"}]
    continuation = {
        "phase": "model",
        "call_payload_version": 2,
        "agent_name": "general",
        "provider": {"provider": "gigachat", "model": "test-model"},
        "messages": conversation,
    }
    saved = sealed["snapshot"]
    await repo.exchange(
        owner,
        Exchange(
            opcode="checkpoint",
            expected_revision=saved["revision"],
            state=saved["state"],
            continuation=continuation,
        ),
    )
    first = call_for(conversation, 0)
    await repo.exchange(owner, Exchange(opcode="grant", call=first))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=first.operation_id))
    receipt = CallReceipt(
        operation_id=first.operation_id,
        status="succeeded",
        prompt=10,
        completion=2,
        finish_reason="length",
        message={"role": "assistant", "content": "Первая часть"},
    )
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
    STAGE = "repository_reload_retains_length"
    repo = HarnessRuntimeRepository(connector)
    stored = await repo.exchange(
        owner,
        Exchange(
            opcode="operation_status",
            operation_id=first.operation_id,
            operation_kind="paid",
        ),
    )
    assert stored["operation_status"]["receipt"]["finish_reason"] == "length"
    before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    conversation = conversation + [
        {"role": "assistant", "content": "Первая часть"},
        {"role": "user", "content": "Продолжи"},
    ]
    continuation.update(messages=conversation, next_step=1, length_continuations=1)
    await repo.exchange(
        owner,
        Exchange(
            opcode="checkpoint",
            expected_revision=before["revision"],
            state=before["state"],
            continuation=continuation,
        ),
    )
    STAGE = "new_step_is_distinct_operation"
    second = call_for(conversation, 1)
    await repo.exchange(owner, Exchange(opcode="grant", call=second))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=second.operation_id))
    final = receipt.model_copy(
        update={"operation_id": second.operation_id, "finish_reason": "stop"}
    )
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=final))
    current = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    STAGE = "counter_reset_is_rejected"
    try:
        await repo.exchange(
            owner,
            Exchange(
                opcode="checkpoint",
                expected_revision=current["revision"],
                state=current["state"],
                continuation={**continuation, "length_continuations": 0},
            ),
        )
    except HarnessFailure as error:
        assert error.code == "operation_conflict"
    else:
        raise AssertionError("counter_reset_admitted")
    STAGE = "duplicate_receipt_preserves_spend"
    await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=final))
    after = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert after == current
    assert len(after["usage"]) == 2 and after["spent_credits"] > 0
    assert after["continuation"]["length_continuations"] == 1
    return [
        "length_receipt_survives_repository_reload",
        "new_model_slot_after_partial",
        "counter_reset_rejected",
        "duplicate_receipt_no_spend_change",
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
