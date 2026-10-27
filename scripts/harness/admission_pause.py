"""Предконтрактный вопрос и передача задания: настоящая одноразовая PostgreSQL-БД."""

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
from service.services.chat.persistence.harness.rebind import rebind_harness
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import (
    CallReceipt,
    Continuation,
    EffectIntent,
    Exchange,
    HarnessFailure,
    PaidCall,
)
from service.shared.task_contract import digest_payload

STAGE = "source_parity"
QUESTION = "Как назвать создаваемый файл?"


async def paid_contract(repo, owner, *, question):
    global STAGE
    prefix = STAGE
    proposal = {
        "kind": "change",
        "criteria": [
            {"criterion_id": "file", "kind": "file", "target": "hello.py"},
        ],
        "needs_clarification": question,
        "question": QUESTION if question else "",
    }
    call = PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=10,
        completion=10,
        request_digest=("a" if question else "b") * 64,
        kind="meta_usage",
    )
    STAGE = prefix + ":grant"
    await repo.exchange(owner, Exchange(opcode="grant", call=call))
    # Метка owning job хранится только на backend и не меняет клиентский digest.
    STAGE = prefix + ":repeat_grant"
    repeated = await repo.exchange(owner, Exchange(opcode="grant", call=call))
    assert repeated["operation"]["status"] == "allocated"
    STAGE = prefix + ":inspect"
    inspected = await repo.exchange(
        owner,
        Exchange(opcode="operation_status", operation_id=call.operation_id, operation_kind="paid"),
    )
    assert inspected["operation_status"]["request_digest"] == digest_payload(
        call.model_dump(mode="json")
    )
    STAGE = prefix + ":dispatch"
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=call.operation_id))
    STAGE = prefix + ":receipt"
    await repo.exchange(
        owner,
        Exchange(
            opcode="call_receipt",
            receipt=CallReceipt(
                operation_id=call.operation_id,
                status="succeeded",
                prompt=10,
                completion=10,
                finish_reason="tool_calls",
                message={
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "contract",
                            "function": {
                                "name": "submit_task_contract",
                                "arguments": json.dumps(proposal),
                            },
                        }
                    ],
                },
            ),
        ),
    )
    STAGE = prefix
    return proposal


async def reject_extra_contract(repo, owner, *, question):
    global STAGE
    prefix = STAGE
    try:
        await paid_contract(repo, owner, question=question)
    except HarnessFailure as error:
        assert error.code == "task_contract_invalid"
    else:
        raise AssertionError("contract_information_window_reset")
    STAGE = prefix


def pending():
    return Continuation(
        phase="admitting",
        admission_active_ms=75,
        next_step=1,
        provider={"provider": "gigachat", "model": "test-model"},
        messages=[
            {"role": "user", "content": "Запрос: PRIVATE_PROBE"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "question",
                        "function": {
                            "name": "ask_user_question",
                            "arguments": json.dumps({"prompt": QUESTION, "choices": []}),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "question", "content": '{"awaiting_user":true}'},
        ],
    )


async def child_fixture(factory, owner, saved):
    child = owner.model_copy(update={"job_id": str(uuid4()), "attempt_id": str(uuid4())})
    reservation = uuid4()
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:job_id,:user_id,'CHAT','PROCESSING',CAST(:body AS jsonb))"
            ),
            {
                **child.params(),
                "body": json.dumps(
                    {"thread_id": child.thread_id, "_execution_attempt_v1": child.attempt_id}
                ),
            },
        )
        await db.execute(
            text(
                "INSERT INTO profile.human_question VALUES (:parent,:job_id,:user_id,:thread_id,"
                "'accepted',CAST(:continuation AS jsonb),"
                "CAST(:prompt AS jsonb),CAST(:answer AS jsonb))"
            ),
            {
                **child.params(),
                "parent": UUID(owner.job_id),
                "continuation": json.dumps(
                    {
                        "model": "test-model",
                        "messages": saved.conversation(),
                        "tool_call_id": "question",
                    }
                ),
                "prompt": json.dumps({"prompt": QUESTION, "choices": []}),
                "answer": json.dumps({"choice_id": None, "text": "hello.py"}),
            },
        )
        await db.execute(
            text(
                "INSERT INTO profile.token_reservations VALUES "
                "(:id,:owner,100,now()+interval '1 hour','reserved',NULL,NULL,NULL)"
            ),
            {"id": reservation, "owner": UUID(owner.user_id)},
        )
        await db.commit()
    return child, reservation


async def exercise(engine):
    global STAGE
    owner, admission = await fixture.seed(engine)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    connector = SimpleNamespace(get_session_context=factory)
    async with engine.begin() as db:
        for name in ("continuation", "prompt", "answer"):
            await db.execute(
                text("ALTER TABLE profile.human_question ADD COLUMN " + name + " jsonb")
            )
    repo = HarnessRuntimeRepository(connector)
    tariff = FrozenPricing(
        entries=[],
        classes=[],
        default={
            "model": "default",
            "incoming": "0.001",
            "outgoing": "0.001",
        },
        credit_unit="0.01",
        margin="1",
        complexity="1",
        minimum=0,
        minimum_margin="1",
        surcharges={},
    )
    await repo.admit(owner, admission, tariff)
    STAGE = "paid_clarification_receipt"
    await paid_contract(repo, owner, question=True)
    await paid_contract(repo, owner, question=True)
    await reject_extra_contract(repo, owner, question=True)
    STAGE = "durable_pause"
    saved = pending()
    paused = await repo.exchange(
        owner, Exchange(opcode="checkpoint", expected_revision=0, continuation=saved)
    )
    assert paused["snapshot"]["state"] is None and paused["snapshot"]["revision"] == 1
    restarted = HarnessRuntimeRepository(connector)
    assert (await restarted.exchange(owner, Exchange(opcode="state")))["snapshot"] == paused[
        "snapshot"
    ]
    STAGE = "unsealed_effect_denied"
    try:
        await restarted.exchange(
            owner,
            Exchange(
                opcode="prepare_effect",
                effect=EffectIntent(
                    operation_id=str(uuid4()),
                    name="ide_write_file",
                    action="write",
                    arguments='{"path":"hello.py"}',
                    source_revision=admission.source_revision,
                ),
            ),
        )
    except HarnessFailure as error:
        assert error.code == "task_permission_denied"
    else:
        raise AssertionError("unsealed_write_admitted")
    STAGE = "pending_question_cannot_seal"
    proposal = {
        "kind": "change",
        "criteria": [
            {"criterion_id": "file", "kind": "file", "target": "hello.py"},
        ],
    }
    try:
        await restarted.exchange(
            owner, Exchange(opcode="seal", expected_revision=1, proposal=proposal)
        )
    except HarnessFailure as error:
        assert error.code == "user_decision_required"
    else:
        raise AssertionError("unanswered_contract_sealed")
    STAGE = "accepted_child_handoff"
    child, reservation = await child_fixture(factory, owner, saved)
    bound = await rebind_harness(
        connector, child, reservation_id=str(reservation), parent_id=UUID(owner.job_id)
    )
    try:
        await repo.exchange(owner, Exchange(opcode="state"))
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("parent_retained_authority")
    restored = (await repo.exchange(bound, Exchange(opcode="state")))["snapshot"]
    assert restored["continuation"] == saved.model_dump(mode="json")
    STAGE = "answered_seal"
    proposal = await paid_contract(repo, bound, question=False)
    proposal = await paid_contract(repo, bound, question=False)
    await reject_extra_contract(repo, bound, question=False)
    sealed = (
        await repo.exchange(bound, Exchange(opcode="seal", expected_revision=1, proposal=proposal))
    )["snapshot"]
    assert sealed["state"]["contract"]["goal"] == admission.goal
    assert sealed["state"]["budget"]["active_ms"] == 75
    assert sealed["continuation"]["next_step"] == 1
    assert json.loads(sealed["continuation"]["clarification"])["answer"]["text"] == "hello.py"
    assert sealed["continuation"]["messages"] == []
    assert len(sealed["usage"]) == 4 and sealed["spent_credits"] >= restored["spent_credits"]
    # Совокупное округление тарифа может оставить то же число credits; новые
    # точные usage receipts всё равно сохраняются, без нового минимума за каждый.
    assert sum(item["prompt"] + item["completion"] for item in restored["usage"]) == 40
    assert sum(item["prompt"] + item["completion"] for item in sealed["usage"]) == 80
    assert [item["kind"] for item in sealed["state"]["contract"]["criteria"]] == ["file", "command"]
    STAGE = "restart_after_seal"
    assert (await restarted.exchange(bound, Exchange(opcode="state")))["snapshot"] == sealed
    return [
        "committed_question_receipt",
        "durable_unsealed_pause",
        "unsealed_effect_denied",
        "unanswered_seal_denied",
        "child_handoff_and_parent_fencing",
        "answer_persisted_at_seal",
        "active_time_provider_and_usage_preserved",
        "mandatory_verification_retained",
        "two_contract_calls_per_information_window",
        "root_and_child_third_call_denied",
        "wire_digest_and_repeated_grant_preserved",
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
                    "code": error.code if isinstance(error, HarnessFailure) else None,
                }
            )
        )
        raise SystemExit(1) from None
