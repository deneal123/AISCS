"""047 repository acceptance only: receipts are synthetic, no command execution.

Disposable PostgreSQL proves durable recipes, verification replacement and repair
limits. Real supervisor execution is accepted separately; never conflate the two.
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.domain.ide.console import CommandResult
from service.services.chat.domain.ide.verification import verify
from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
from service.shared.harness_protocol import EffectIntent, Exchange, HarnessFailure

STAGE = "source_parity"


async def constraint_rejects(db, sql, params):
    try:
        await db.execute(text(sql), params)
    except IntegrityError as error:
        cause = getattr(error.orig, "__cause__", None)
        assert getattr(error.orig, "sqlstate", None) == "23514"
        assert getattr(cause, "constraint_name", None) == "ck_harness_command_body"
        await db.rollback()
    else:
        raise AssertionError("command_body_guard_missing")


async def intent(repo, owner, spec):
    operation = uuid4()
    await repo.exchange(
        owner,
        Exchange(
            opcode="prepare_effect",
            effect=EffectIntent(
                operation_id=str(operation),
                name="ide_run_command",
                action="exec",
                arguments=spec.model_dump_json(),
                source_revision=(await repo.exchange(owner, Exchange(opcode="state")))["snapshot"][
                    "state"
                ]["source_revision"],
            ),
        ),
    )
    await repo.exchange(owner, Exchange(opcode="dispatch_effect", operation_id=str(operation)))
    return operation


async def finish(repo, owner, operation, snapshot_id, spec, *, passed):
    await repo.pin_snapshot(owner, operation, snapshot_id, "b" * 64, "r1")
    await repo.transition(owner, operation, state="ready")
    await repo.transition(
        owner, operation, state="dispatching", engine_id="c" * 64, container_id="d" * 64
    )
    await repo.transition(owner, operation, state="running")
    result = CommandResult(
        exit_code=0 if passed else 1,
        stdout="hello\n" if passed else "",
        stderr="" if passed else "synthetic failing check",
        truncated=False,
        timed_out=False,
        duration_sec=0.01,
    )
    updates = dict(
        state="completed" if passed else "failed",
        result=result,
        final_revision="r2",
        cleanup_confirmed=True,
        output_complete=True,
        verification=verify(spec, result, None),
    )
    receipt = await repo.transition(owner, operation, **updates)
    assert await repo.transition(owner, operation, **updates) == receipt


async def blocked_output_does_not_repeat(base, support, engine, spec):
    owner, allocation, factory, connector, repo = await support.fixture(base, engine)
    checkpoint, _ = await support.checkpoints(factory, owner, allocation)
    operation = await intent(repo, owner, spec)
    await repo.admit_command(owner, operation, spec, "fixture-workspace")
    await repo.pin_snapshot(owner, operation, checkpoint, "b" * 64, "r1")
    await repo.transition(owner, operation, state="ready")
    await repo.transition(
        owner, operation, state="dispatching", engine_id="c" * 64, container_id="d" * 64
    )
    await repo.transition(owner, operation, state="running")
    await repo.transition(
        owner,
        operation,
        state="failed",
        result=None,
        final_revision="r2",
        cleanup_confirmed=True,
        output_complete=False,
        failure_reason="output_unavailable",
        verification=verify(spec, None, None),
    )
    # Ни смена ID, ни обход через shell не создают второй command record.
    repo = IdeCommandRepository(connector)
    for candidate in (spec, CommandSpec(profile="shell", command="python3 a.py")):
        rejected = await intent(repo, owner, candidate)
        await support.denied(
            repo.admit_command(owner, rejected, candidate, "fixture-workspace"),
            "verification_unavailable",
        )
        async with factory() as db:
            row = (
                (
                    await db.execute(
                        text(
                            "SELECT command,receipt FROM profile.harness_operation "
                            "WHERE operation_id=:id"
                        ),
                        {"id": rejected},
                    )
                )
                .mappings()
                .one()
            )
            assert row["command"] is None and row["receipt"]["status"] == "failed"
    state = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]["state"]
    assert state["repairs"] == 0
    async with factory() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT command_pins FROM profile.ide_checkpoint_intent WHERE checkpoint_id=:id"
                ),
                {"id": checkpoint},
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM profile.harness_operation "
                    "WHERE task_id=:task AND command IS NOT NULL"
                ),
                {"task": UUID(owner.task_id)},
            )
            == 1
        )


async def exercise(base, support, engine):
    global STAGE
    owner, allocation, factory, connector, repo = await support.fixture(base, engine)
    oldest, _ = await support.checkpoints(factory, owner, allocation)
    spec = CommandSpec(
        profile="python_script",
        target="a.py",
        expected_stdout="hello\n",
        criterion_id="verify_project",
    )
    STAGE = "verified_receipt_persists"
    operation = await intent(repo, owner, spec)
    await repo.admit_command(owner, operation, spec, "fixture-workspace")
    await finish(repo, owner, operation, oldest, spec, passed=True)
    repo = IdeCommandRepository(connector)
    state = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]["state"]
    assert state["source_revision"] == "r2"
    assert (
        next(e for e in state["evidence"] if e["criterion_id"] == "verify_project")["outcome"]
        == "passed"
    )

    STAGE = "recipe_immutable_across_operations"
    changed = spec.model_copy(update={"expected_stdout": "different\n"})
    rejected = await intent(repo, owner, changed)
    await support.denied(
        repo.admit_command(owner, rejected, changed, "fixture-workspace"), "operation_conflict"
    )
    STAGE = "rejected_recipe_receipt"
    async with factory() as db:
        rejected_receipt = await db.scalar(
            text("SELECT receipt FROM profile.harness_operation WHERE operation_id=:operation"),
            {"operation": rejected},
        )
        assert rejected_receipt["status"] == "failed"
        assert rejected_receipt["charged"] is False and not rejected_receipt["evidence"]
        saved = await db.scalar(
            text("SELECT verification_recipes FROM profile.harness_task WHERE task_id=:task"),
            {"task": UUID(owner.task_id)},
        )
        assert saved["verify_project"]["expected_stdout"] == "hello\n"

    STAGE = "failure_replaces_same_revision_pass"
    for repairs in range(3):
        operation = await intent(repo, owner, spec)
        await repo.admit_command(owner, operation, spec, "fixture-workspace")
        await finish(repo, owner, operation, oldest, spec, passed=False)
        state = (await repo.exchange(owner, Exchange(opcode="state")))["snapshot"]["state"]
        assert state["repairs"] == repairs
        facts = [e for e in state["evidence"] if e["criterion_id"] == "verify_project"]
        assert len(facts) == 1 and facts[0]["outcome"] == "failed"
    STAGE = "two_repairs_survive_repository_recreation"
    repo = IdeCommandRepository(connector)
    operation = await intent(repo, owner, spec)
    await support.denied(
        repo.admit_command(owner, operation, spec, "fixture-workspace"), "usage_limit_exceeded"
    )

    STAGE = "command_json_size_guard"
    async with factory() as db:
        await constraint_rejects(
            db,
            "UPDATE profile.harness_operation SET command=command || "
            "jsonb_build_object('fixture_padding',CAST(:body AS text)) "
            "WHERE task_id=:task AND command IS NOT NULL",
            {"task": UUID(owner.task_id), "body": "x" * 524288},
        )
    STAGE = "command_json_state_guard"
    async with factory() as db:
        await constraint_rejects(
            db,
            "UPDATE profile.harness_operation SET command_state='unknown' "
            "WHERE task_id=:task AND command_state='completed'",
            {"task": UUID(owner.task_id)},
        )
    return [
        "verified_receipt_persists",
        "recipe_immutable_across_operations",
        "known_recipe_refusal_does_not_block_followup",
        "failure_replaces_same_revision_pass",
        "two_repairs_survive_repository_recreation",
        "command_json_size_guard",
        "command_json_state_guard",
    ]


async def main():
    global STAGE
    payload = json.load(sys.stdin)
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in payload["files"].items()
    )
    base, support = ModuleType("runtime_probe"), ModuleType("command_probe")
    exec(compile(payload["runtime"], "runtime_probe", "exec"), base.__dict__)
    exec(compile(payload["commands"], "command_probe", "exec"), support.__dict__)
    os.environ["HARNESS__IDE_ENABLED"] = "true"
    os.environ["HARNESS__IDE_COMMANDS_ENABLED"] = "true"
    async with base.disposable() as engine:
        cases = await exercise(base, support, engine)
    STAGE = "blocked_output_no_repeat"
    async with base.disposable() as engine:
        await blocked_output_does_not_repeat(
            base,
            support,
            engine,
            CommandSpec(
                profile="python_script",
                target="a.py",
                expected_stdout="hello\n",
                criterion_id="verify_project",
            ),
        )
    cases.append("blocked_verification_no_command_repeat")
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(
            json.dumps(
                {
                    "failure": "verification_probe_failed",
                    "stage": STAGE,
                    "error_type": type(error).__name__,
                    "failure_code": error.code if isinstance(error, HarnessFailure) else "internal",
                }
            )
        )
        raise SystemExit(1) from None
