"""Настоящий PG-журнал: правка UI инвалидирует read без command receipt."""

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
from service.services.chat.persistence.harness.admission.workspace_scope import bind_workspace
from service.services.chat.persistence.harness.commands.invalidation import (
    invalidate_external_write,
)
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import Exchange
from service.shared.task_contract import CompletionVerifier, TaskEvidence, TaskState

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
    saved = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
    proof = TaskEvidence(
        criterion_id="source",
        operation_id=str(uuid4()),
        kind="read",
        target="a.py",
        source_revision=saved["state"]["source_revision"],
        digest="a" * 64,
        outcome="passed",
    )
    state = TaskState.model_validate(saved["state"]).advance(evidence=[proof], rounds=15, repairs=1)
    workspace = "a" * 32
    async with factory() as db:
        # Только столбец, используемый production invalidation SQL; команды в этой
        # PG-пробе не создаются. Это не полный backend/workspace worker acceptance.
        await db.execute(
            text("ALTER TABLE profile.harness_operation ADD command_workspace_id text")
        )
        await db.execute(
            text(
                "ALTER TABLE profile.human_question ADD surface text,ADD project_id text,"
                "ADD expires_at timestamptz"
            )
        )
        await db.execute(
            text(
                "UPDATE profile.harness_task SET "
                "checkpoint=jsonb_set(checkpoint,'{state}',CAST(:state AS jsonb)),"
                "admission=admission || "
                "jsonb_build_object('workspace_id',CAST(:workspace AS text)) "
                "WHERE task_id=:task"
            ),
            {"state": state.model_dump_json(), "workspace": workspace, "task": UUID(owner.task_id)},
        )
        await db.commit()

    async def current_state():
        async with factory() as db:
            raw = await db.scalar(
                text("SELECT checkpoint->'state' FROM profile.harness_task WHERE task_id=:task"),
                {"task": UUID(owner.task_id)},
            )
            return TaskState.model_validate(raw)

    STAGE = "wrong_workspace"
    await invalidate_external_write(connector, "b" * 32)
    assert await current_state() == state
    STAGE = "read_without_command_invalidated"
    await invalidate_external_write(connector, workspace)
    changed = await current_state()
    assert changed.source_revision != state.source_revision
    assert CompletionVerifier.evaluate(changed)["unchecked"] == ["source"]
    assert changed.evidence == state.evidence
    STAGE = "terminal_history_unchanged"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET status='SUCCESS' WHERE id=:job"),
            {"job": UUID(owner.job_id)},
        )
        await db.commit()
    await invalidate_external_write(connector, workspace)
    assert await current_state() == changed
    STAGE = "parked_question_read_invalidated"
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                '\'{"metadata":{"task_result":{"status":"waiting_user"}}}\'::jsonb '
                "WHERE id=:job"
            ),
            {"job": UUID(owner.job_id)},
        )
        await db.execute(
            text(
                "INSERT INTO profile.human_question "
                "(source_job_id,user_id,thread_id,state,surface,project_id,expires_at) "
                "VALUES (:job_id,:user_id,:thread_id,'pending','ide',:project_id,"
                "now()+interval '1 hour')"
            ),
            {**owner.params(), "project_id": owner.project_id},
        )
        await db.commit()
    await invalidate_external_write(connector, workspace)
    parked = await current_state()
    assert parked.source_revision != changed.source_revision
    assert parked.evidence == state.evidence and parked.rounds == 15 and parked.repairs == 1
    assert CompletionVerifier.evaluate(parked)["unchecked"] == ["source"]
    STAGE = "expired_question_history_unchanged"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.human_question SET expires_at=now()-interval '1 second'")
        )
        await db.commit()
    await invalidate_external_write(connector, workspace)
    assert await current_state() == parked
    STAGE = "accepted_child_read_invalidated"
    child = uuid4()
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:child,:owner,'CHAT','NEW','{}')"
            ),
            {"child": child, "owner": UUID(owner.user_id)},
        )
        await db.execute(
            text("UPDATE profile.human_question SET state='accepted',resume_job_id=:child"),
            {"child": child},
        )
        await db.commit()
    # Accepted answer остаётся действительным после срока самого вопроса;
    # незапущенный child всё ещё обязан увидеть новую версию исходников.
    await invalidate_external_write(connector, workspace)
    accepted = await current_state()
    assert accepted.source_revision != parked.source_revision
    assert accepted.evidence == parked.evidence and accepted.rounds == 15 and accepted.repairs == 1
    STAGE = "terminal_child_history_unchanged"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET status='SUCCESS' WHERE id=:child"),
            {"child": child},
        )
        await db.commit()
    await invalidate_external_write(connector, workspace)
    assert await current_state() == accepted
    STAGE = "foreign_question_scope_unchanged"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET status='NEW' WHERE id=:child"),
            {"child": child},
        )
        await db.execute(
            text("UPDATE profile.human_question SET user_id=:other"), {"other": uuid4()}
        )
        await db.commit()
    await invalidate_external_write(connector, workspace)
    assert await current_state() == accepted
    STAGE = "legacy_binding_invalidates_unobserved_evidence"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET status='PROCESSING' WHERE id=:job"),
            {"job": UUID(owner.job_id)},
        )
        await db.execute(
            text(
                "UPDATE profile.harness_task SET admission=admission-'workspace_id',"
                "checkpoint=jsonb_set(checkpoint,'{state}',CAST(:state AS jsonb)) "
                "WHERE task_id=:task"
            ),
            {"task": UUID(owner.task_id), "state": state.model_dump_json()},
        )
        row = (
            (
                await db.execute(
                    text(
                        "SELECT t.*,j.payload AS job_payload FROM profile.harness_task t "
                        "JOIN profile.user_launch j ON j.id=t.active_job_id "
                        "WHERE t.task_id=:task FOR UPDATE OF t"
                    ),
                    {"task": UUID(owner.task_id)},
                )
            )
            .mappings()
            .one()
        )
        await bind_workspace(db, row, owner, workspace)
        await db.commit()
    rebound = await current_state()
    assert rebound.source_revision != state.source_revision
    assert CompletionVerifier.evaluate(rebound)["unchecked"] == ["source"]
    assert rebound.evidence == state.evidence
    return [
        "wrong_workspace_unchanged",
        "read_without_command_invalidated",
        "terminal_history_unchanged",
        "parked_question_read_invalidated",
        "expired_question_history_unchanged",
        "accepted_child_read_invalidated",
        "terminal_child_history_unchanged",
        "foreign_question_scope_unchanged",
        "legacy_binding_invalidates_unobserved_evidence",
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
        cases = await exercise(engine)
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
