"""Принятие рекомендации только по журналу модели и executor evidence в одноразовой БД."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from scripts.harness import runtime as fixture
from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.persistence.harness.lessons import read_lessons
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import Exchange, HarnessFailure, PaidCall, Snapshot
from service.shared.harness_refinement import RefinementAttempt, render_refinement
from service.shared.task_contract import digest_payload

STAGE = "source_parity"


async def model_receipt(repo, owner, body, message, *, step=None, reason="stop"):
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
    call = PaidCall(
        operation_id=str(uuid4()),
        provider="local",
        model="test-model",
        prompt=len(encoded.encode()) + 1024,
        completion=50,
        request_digest=digest_payload(body),
        canonical_request=encoded,
        continuation_step=step,
        kind="chat" if step is not None else "meta_usage",
    )
    await repo.exchange(owner, Exchange(opcode="grant", call=call))
    await repo.exchange(owner, Exchange(opcode="dispatch", operation_id=call.operation_id))
    await repo.exchange(
        owner,
        Exchange(
            opcode="call_receipt",
            receipt={
                "operation_id": call.operation_id,
                "status": "succeeded",
                "prompt": 10,
                "completion": 5,
                "message": message,
                "finish_reason": reason,
            },
        ),
    )
    return call.operation_id


async def checkpoint(repo, owner, continuation, **updates):
    saved = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    state = {**saved["state"], **updates}
    await repo.exchange(
        owner,
        Exchange(
            opcode="checkpoint",
            expected_revision=saved["revision"],
            continuation=continuation,
            state=state,
        ),
    )


async def exercise(engine, *, probe_guidance=True):
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
    await repo.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "analysis",
                "criteria": [{"criterion_id": "source", "kind": "read", "target": "a.py"}],
            },
        ),
    )
    messages = [{"role": "user", "content": "Прочитай a.py"}]
    continuation = {
        "phase": "model",
        "call_payload_version": 2,
        "next_step": 0,
        "provider": {"provider": "local", "model": "test-model"},
        "messages": messages,
    }
    await checkpoint(repo, owner, continuation)
    tool = {
        "type": "function",
        "function": {"name": "ide_read_file", "parameters": {"type": "object"}},
    }
    body = {"model": "test-model", "messages": messages, "tools": [tool], "max_tokens": 50}
    baseline = await model_receipt(
        repo, owner, body, {"role": "assistant", "content": "Ответ без чтения"}, step=0
    )
    proposal = {"instruction": "Перед ответом прочитай запрошенный файл.", "tools": []}
    proposal_id = await model_receipt(
        repo,
        owner,
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Предложи исправление"}],
            "max_tokens": 50,
        },
        {"role": "assistant", "content": json.dumps(proposal, ensure_ascii=False)},
    )
    candidate = RefinementAttempt(
        baseline_operation=baseline,
        proposal_operation=proposal_id,
        proposal=proposal,
        probe_step=1,
        baseline_evidence_count=0,
    )
    messages = messages + [{"role": "user", "content": render_refinement(candidate.proposal)}]
    continuation.update(
        next_step=1, messages=messages, refinement=candidate.model_dump(mode="json")
    )
    STAGE = "forged_adoption_rejected"
    try:
        await checkpoint(
            repo,
            owner,
            {**continuation, "refinement": candidate.model_copy(update={"adopted": True})},
        )
    except HarnessFailure as error:
        assert error.code == "operation_conflict"
    else:
        raise AssertionError("forged_adoption_accepted")
    await checkpoint(repo, owner, continuation, protocol_repairs=1)
    STAGE = "candidate_survives_reload"
    repo = HarnessRuntimeRepository(connector)
    saved = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    assert saved["continuation"]["refinement"] == candidate.model_dump(mode="json")
    assert (await repo.exchange(owner, Exchange(opcode="result")))["result"][
        "status"
    ] != "completed"
    STAGE = "probe_then_trusted_evidence"
    if not probe_guidance:
        # Допустимый checkpoint сохранил candidate, но удалил его из контекста.
        # Успех задачи после этого не доказывает работу самой рекомендации.
        messages = messages[:-1]
        continuation["messages"] = messages
        await checkpoint(repo, owner, continuation, protocol_repairs=1)
    await model_receipt(
        repo,
        owner,
        {**body, "messages": messages},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "read-1",
                    "type": "function",
                    "function": {"name": "ide_read_file", "arguments": '{"path":"a.py"}'},
                }
            ],
        },
        step=1,
        reason="tool_calls",
    )
    operation = str(uuid4())
    await repo.exchange(
        owner,
        Exchange(
            opcode="prepare_effect",
            effect={
                "operation_id": operation,
                "name": "ide_read_file",
                "arguments": '{"path":"a.py"}',
                "action": "read",
                "source_revision": "r1",
            },
        ),
    )
    await repo.exchange(owner, Exchange(opcode="dispatch_effect", operation_id=operation))
    proof = {
        "operation_id": operation,
        "criterion_id": "source",
        "kind": "read",
        "target": "a.py",
        "source_revision": "r1",
        "digest": "a" * 64,
        "outcome": "passed",
    }
    await repo.exchange(
        owner,
        Exchange(
            opcode="effect_receipt",
            effect_result={
                "operation_id": operation,
                "status": "succeeded",
                "text": "Проверенный исходник",
                "charged": False,
                "evidence": [proof],
            },
        ),
    )
    await checkpoint(repo, owner, continuation, protocol_repairs=1, evidence=[proof])
    STAGE = "verified_adoption_is_idempotent"
    result = (await repo.exchange(owner, Exchange(opcode="result")))["result"]
    assert result["status"] == "completed"
    first = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    if not probe_guidance:
        assert first["continuation"]["refinement"]["adopted"] is False
        async with connector.get_session_context() as db:
            await db.execute(
                text("UPDATE profile.user_launch SET status='SUCCESS' WHERE id=:id"),
                {"id": owner.params()["job_id"]},
            )
            await store_terminal(db, owner, result)
            current = Snapshot.model_validate(first)
            row = {"user_id": owner.params()["user_id"], "task_id": uuid4()}
            assert await read_lessons(db, row, current) == []
        return ["unused_guidance_not_adopted", "unused_guidance_not_reused"]
    assert first["continuation"]["refinement"]["adopted"] is True
    assert (await repo.exchange(owner, Exchange(opcode="result")))["result"] == result
    assert (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"] == first
    STAGE = "lesson_scope"
    current = Snapshot.model_validate(first)
    async with connector.get_session_context() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET status='SUCCESS' WHERE id=:id"),
            {"id": owner.params()["job_id"]},
        )
        row = {"user_id": owner.params()["user_id"], "task_id": uuid4()}
        # SUCCESS транспорта и предварительного adopted недостаточно для библиотеки.
        assert await read_lessons(db, row, current) == []
        for status in ("partial", "blocked", "waiting_user", "cancelled"):
            terminal = {
                **result,
                "status": status,
                "verified": False,
                "blocker": "cancelled" if status == "cancelled" else "verification_failed",
            }
            await store_terminal(db, owner, terminal)
            assert await read_lessons(db, row, current) == []
        await store_terminal(db, owner, {"schema_version": 1, "status": "completed"})
        assert await read_lessons(db, row, current) == []
        await store_terminal(db, owner, {**result, "references": []})
        assert await read_lessons(db, row, current) == []
        await store_terminal(db, owner, result)
        assert await read_lessons(db, row, current) == [proposal]
        assert await read_lessons(db, {**row, "user_id": uuid4()}, current) == []
        changed = current.model_copy(
            update={"admission": current.admission.model_copy(update={"generation": "different"})}
        )
        assert await read_lessons(db, row, changed) == []
        changed_goal = current.model_copy(
            update={
                "admission": current.admission.model_copy(
                    update={"goal": "Иная задача в том же проекте"}
                )
            }
        )
        assert await read_lessons(db, row, changed_goal) == []
        assert await read_lessons(db, {**row, "task_id": owner.params()["task_id"]}, current) == []
    return [
        "candidate_reloaded",
        "self_adoption_rejected",
        "pending_not_adopted",
        "verified_adopted",
        "repeat_unchanged",
        "lesson_requires_final_task_result",
        "lesson_user_project_generation_scope",
    ]


async def store_terminal(db, owner, result):
    await db.execute(
        text(
            "UPDATE profile.user_launch SET payload=jsonb_set(payload,'{metadata}', "
            "COALESCE(payload->'metadata','{}'::jsonb) || "
            "jsonb_build_object('task_result',CAST(:result AS jsonb)),true) WHERE id=:job"
        ),
        {"job": owner.params()["job_id"], "result": json.dumps(result)},
    )


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
    cases = []
    for probe_guidance in (True, False):
        async with fixture.disposable() as engine:
            async with asyncio.timeout(40):
                cases.extend(await exercise(engine, probe_guidance=probe_guidance))
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
