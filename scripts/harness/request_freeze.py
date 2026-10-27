"""Изолированная PG-проверка единственного замороженного запроса на шаг задачи."""

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


def planned_call(*, temperature=0.0, text="Прочитай README"):
    body = json.dumps(
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": text}],
            "temperature": temperature,
            "max_tokens": 20,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=len(body.encode()) + 1024,
        completion=20,
        request_digest=digest_payload(json.loads(body)),
        canonical_request=body,
        continuation_step=0,
    )


async def exchange(repo, owner, request):
    try:
        return await repo.exchange(owner, request)
    except HarnessFailure as error:
        return error.code


async def exercise(engine):
    global STAGE
    owner, admission = await fixture.seed(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = HarnessRuntimeRepository(SimpleNamespace(get_session_context=factory))
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
    current = await repo.exchange(
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
    saved = current["snapshot"]
    await repo.exchange(
        owner,
        Exchange(
            opcode="checkpoint",
            expected_revision=saved["revision"],
            state=saved["state"],
            continuation={
                "phase": "model",
                "agent_name": "general",
                "call_payload_version": 2,
                "provider": {"provider": "gigachat", "model": "test-model"},
                "messages": [{"role": "user", "content": "Прочитай README"}],
            },
        ),
    )
    STAGE = "parallel_request_freeze"
    calls = [planned_call(temperature=index / 10) for index in range(4)]
    outcomes = await asyncio.gather(
        *(exchange(repo, owner, Exchange(opcode="grant", call=call)) for call in calls)
    )
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    assert outcomes.count("provider_state_incompatible") == 3
    winner = calls[next(index for index, value in enumerate(outcomes) if isinstance(value, dict))]
    async with factory() as db:
        requests = (
            (await db.execute(text("SELECT request FROM profile.harness_grant"))).scalars().all()
        )
        assert len(requests) == 1 and requests[0]["canonical_request"] == winner.canonical_request
        assert requests[0]["continuation_step"] == 0
    STAGE = "same_request_receipt_replay"
    assert (await repo.exchange(owner, Exchange(opcode="grant", call=winner)))["operation"][
        "status"
    ] == "allocated"
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=winner.operation_id))
    before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert (
        await exchange(repo, owner, Exchange(opcode="grant", call=planned_call()))
        == "provider_state_incompatible"
    )
    assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == before
    for status in ("unknown", "succeeded"):
        receipt = CallReceipt(
            operation_id=winner.operation_id,
            status=status,
            prompt=12 if status == "succeeded" else 0,
            message={"role": "assistant", "content": "Синтетический ответ"}
            if status == "succeeded"
            else None,
        )
        await repo.exchange(owner, Exchange(opcode="call_receipt", receipt=receipt))
        before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
        outcome = await exchange(repo, owner, Exchange(opcode="grant", call=planned_call()))
        if status == "unknown":
            assert outcome == "provider_state_incompatible"
        else:
            assert outcome["operation"]["operation_id"] == winner.operation_id
            assert outcome["operation"]["receipt"]["operation_id"] == winner.operation_id
            assert (
                await exchange(
                    repo, owner, Exchange(opcode="grant", call=planned_call(text="Иная задача"))
                )
                == "provider_state_incompatible"
            )
        assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == before
    repeated = await repo.exchange(owner, Exchange(opcode="grant", call=winner))
    assert repeated["operation"]["receipt"]["prompt"] == 12
    before = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    replays = await asyncio.gather(
        *(
            repo.exchange(owner, Exchange(opcode="grant", call=planned_call(temperature=0.9)))
            for _ in range(4)
        )
    )
    assert all(value["operation"]["operation_id"] == winner.operation_id for value in replays)
    assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == before
    STAGE = "codec_transition_fenced"
    changed = {**before["continuation"], "call_payload_version": 1}
    assert (
        await exchange(
            repo,
            owner,
            Exchange(
                opcode="checkpoint",
                expected_revision=before["revision"],
                state=before["state"],
                continuation=changed,
            ),
        )
        == "provider_state_incompatible"
    )
    assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == before
    async with factory() as db:
        assert (
            await db.scalar(
                text("SELECT count(*) FROM profile.harness_grant WHERE task_id=:task"),
                {"task": UUID(owner.task_id)},
            )
            == 1
        )
    return [
        "one_request_per_step",
        "frozen_body_persisted",
        "changed_request_no_dispatch",
        "receipt_and_budget_unchanged",
        "completed_slot_replay_original_id",
        "codec_transition_fenced",
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
