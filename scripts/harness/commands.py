"""Disposable PG acceptance for command admission/gates/pins; no process dispatch.

The host provides the runtime fixture module and verifies mounted source hashes.
Only closed case names leave this process, never SQL parameters or diagnostics.
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.chat.domain.ide.commands import CommandSpec
from service.services.chat.domain.ide.runtime import RepositoryScope, allocation_generation_tag
from service.services.chat.persistence.harness.commands.gate import (
    IdeCommandBusy,
    require_mutation_available,
)
from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
from service.services.chat.persistence.ide.checkpoints.restore import IdeRestoreRepository
from service.services.chat.persistence.ide.checkpoints.retention import (
    IdeCheckpointRetentionRepository,
)
from service.shared.harness_protocol import EffectIntent, EffectResult, Exchange, HarnessFailure

STAGE = "source_parity"


async def denied(awaitable, code):
    try:
        await awaitable
    except HarnessFailure as error:
        assert error.code == code
    else:
        raise AssertionError("expected_closed_denial")


async def fixture(base, engine):
    project, allocation = uuid4(), uuid4()
    owner, admission = await base.seed(
        engine, project_id=str(project), generation=allocation_generation_tag(allocation)
    )
    async with engine.begin() as db:
        for name in (
            "032_ide_repositories.py",
            "033_ide_runtime_claims.py",
            "034_ide_checkpoint_revisions.py",
            "039_ide_restore_journal.py",
            "040_ide_checkpoint_accounting.py",
            "042_ide_checkpoint_orphan_cleanup.py",
            "046_ide_command_operations.py",
            "047_command_receipt_boundaries.py",
        ):
            await db.run_sync(lambda connection, name=name: base.migrate(connection, name))
        args = {**owner.params(), "project": project, "allocation": allocation}
        await db.execute(
            text(
                "INSERT INTO profile.ide_repository(repository_id,thread_id,user_id,"
                "creation_intent_id,name) "
                "VALUES (:project,:thread_id,:user_id,:project,'fixture')"
            ),
            args,
        )
        await db.execute(
            text(
                "INSERT INTO profile.ide_repository_runtime(repository_id,allocation_id,"
                "expires_at,state) "
                "VALUES (:project,:allocation,extract(epoch FROM now())+600,'ready')"
            ),
            args,
        )
    factory = async_sessionmaker(engine, class_=base.ProbeSession, expire_on_commit=False)
    connector = SimpleNamespace(get_session_context=factory)
    repository = IdeCommandRepository(connector)
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
    await repository.admit(owner, admission, tariff)
    await repository.exchange(
        owner,
        Exchange(
            opcode="seal",
            expected_revision=0,
            proposal={
                "kind": "change",
                "criteria": [{"criterion_id": "file", "kind": "file", "target": "a.py"}],
            },
        ),
    )
    return owner, allocation, factory, connector, repository


async def effect(repo, owner):
    spec = CommandSpec(profile="python_script", target="a.py", expected_stdout="hello\n")
    intent = EffectIntent(
        operation_id=str(uuid4()),
        name="ide_run_command",
        action="exec",
        arguments=spec.model_dump_json(),
        source_revision="r1",
    )
    await repo.exchange(owner, Exchange(opcode="prepare_effect", effect=intent))
    await repo.exchange(owner, Exchange(opcode="dispatch_effect", operation_id=intent.operation_id))
    return UUID(intent.operation_id), spec


async def checkpoints(factory, owner, allocation):
    oldest, newest = uuid4(), None
    async with factory() as db:
        for number in range(12):
            identity = oldest if number == 0 else uuid4()
            newest = identity
            await db.execute(
                text(
                    "INSERT INTO profile.ide_checkpoint_intent(repository_id,checkpoint_id,user_id,"
                    "thread_id,allocation_id,sha256,size,storage_namespace,state,"
                    "published_at,upload_settled_at) "
                    "VALUES (:project,:id,:user_id,:thread_id,:allocation,:digest,100,:ns,"
                    "'published',"
                    "now()+(:n * interval '1 second'),now())"
                ),
                {
                    **owner.params(),
                    "project": UUID(owner.project_id),
                    "id": identity,
                    "allocation": allocation,
                    "digest": "b" * 64,
                    "ns": "e" * 64,
                    "n": number,
                },
            )
        await db.execute(
            text(
                "INSERT INTO profile.ide_repository_head(repository_id,checkpoint_id) "
                "VALUES (:project,:id)"
            ),
            {"project": UUID(owner.project_id), "id": newest},
        )
        await db.commit()
    return oldest, newest


async def exercise(base, engine):
    global STAGE
    STAGE = "fixture"
    owner, allocation, factory, connector, repo = await fixture(base, engine)
    identity, spec = await effect(repo, owner)
    STAGE = "admission_replay"
    first, second = await asyncio.gather(
        *[repo.admit_command(owner, identity, spec, "fixture-workspace") for _ in range(2)]
    )
    assert first == second and first.state == "preparing"
    await denied(
        repo.admit_command(
            owner, identity, spec.model_copy(update={"target": "b.py"}), "fixture-workspace"
        ),
        "operation_conflict",
    )
    STAGE = "snapshot_pin"
    oldest, newest = await checkpoints(factory, owner, allocation)
    await denied(
        repo.pin_snapshot(owner, identity, oldest, "f" * 64, "tree1"), "verification_unavailable"
    )
    pinned = await repo.pin_snapshot(owner, identity, oldest, "b" * 64, "tree1")
    assert (await repo.pin_snapshot(owner, identity, oldest, "b" * 64, "tree1")) == pinned
    scope = RepositoryScope(UUID(owner.thread_id), UUID(owner.user_id), UUID(owner.project_id))
    retention = IdeCheckpointRetentionRepository(connector)
    assert (
        await retention.retire_history(
            scope, after_checkpoint_id=newest, storage_namespace="e" * 64
        )
        == []
    )
    async with factory() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT command_pins FROM profile.ide_checkpoint_intent WHERE checkpoint_id=:id"
                ),
                {"id": oldest},
            )
            == 1
        )
    STAGE = "durable_gate"
    try:
        await require_mutation_available(connector, "fixture-workspace", "write")
    except IdeCommandBusy:
        pass
    else:
        raise AssertionError("mutation_was_allowed")
    await require_mutation_available(connector, "fixture-workspace", "capture")
    # A new repository object models an observer losing all process-local state.
    assert await IdeCommandRepository(connector).command_status(owner, identity) == pinned
    STAGE = "generation_and_stop"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.ide_repository_runtime SET allocation_id=:id"), {"id": uuid4()}
        )
        await db.commit()
    await denied(repo.transition(owner, identity, state="ready"), "binding_changed")
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.ide_repository_runtime SET allocation_id=:id"), {"id": allocation}
        )
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_cancel_requested_v1',true)"
            )
        )
        await db.commit()
    await denied(repo.transition(owner, identity, state="ready"), "cancelled")
    stale = owner.model_copy(update={"attempt_id": str(uuid4())})
    await denied(repo.command_status(stale, identity), "harness_fenced")
    STAGE = "terminal_once"
    cancelled = await repo.transition(owner, identity, state="cancelled")
    assert await repo.transition(owner, identity, state="cancelled") == cancelled
    await require_mutation_available(connector, "fixture-workspace", "write")
    retired = await retention.retire_history(
        scope, after_checkpoint_id=newest, storage_namespace="e" * 64
    )
    assert [item.intent.blob.checkpoint_id for item in retired] == [oldest]
    async with factory() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT command_pins FROM profile.ide_checkpoint_intent WHERE checkpoint_id=:id"
                ),
                {"id": oldest},
            )
            == 0
        )
        receipt = await db.scalar(
            text("SELECT receipt FROM profile.harness_operation WHERE operation_id=:id"),
            {"id": identity},
        )
        assert (
            receipt["status"] == "failed"
            and receipt["charged"] is False
            and not receipt["evidence"]
        )
    STAGE = "unknown_operation"
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.user_launch SET payload=payload - '_cancel_requested_v1'")
        )
        await db.commit()
    second_id, second_spec = await effect(repo, owner)
    await repo.admit_command(owner, second_id, second_spec, "fixture-workspace")
    await repo.pin_snapshot(owner, second_id, newest, "b" * 64, "tree2")
    await repo.transition(owner, second_id, state="ready")
    await repo.transition(
        owner, second_id, state="dispatching", engine_id="c" * 64, container_id="d" * 64
    )
    await repo.transition(owner, second_id, state="running")
    unknown = await repo.transition(owner, second_id, state="unknown")
    await repo.exchange(
        owner,
        Exchange(
            opcode="effect_receipt",
            effect_result=EffectResult(
                operation_id=str(second_id),
                status="unknown",
                text="operation_unknown",
            ),
        ),
    )
    await denied(repo.transition(owner, second_id, state="dispatching"), "operation_unknown")
    await denied(repo.transition(owner, second_id, state="cancelled"), "verification_missing")
    assert await IdeCommandRepository(connector).command_status(owner, second_id) == unknown
    restore = await IdeRestoreRepository(connector).reserve(
        scope, uuid4(), newest, allocation, ttl_sec=60
    )
    assert restore.failure == "command_busy" and not restore.dispatch
    async with factory() as db:
        assert (
            await db.scalar(
                text(
                    "SELECT command_pins FROM profile.ide_checkpoint_intent WHERE checkpoint_id=:id"
                ),
                {"id": newest},
            )
            == 1
        )
    await repo.transition(owner, second_id, state="cancelled", cleanup_confirmed=True)
    await require_mutation_available(connector, "fixture-workspace", "write")
    return [
        "command_replay",
        "intent_immutable",
        "snapshot_pin_once",
        "pinned_retention",
        "durable_mutation_gate",
        "generation_fence",
        "stop_before_dispatch",
        "stale_attempt_denied",
        "terminal_unpin_once",
        "unknown_blocks_redis_independent",
        "unknown_cleanup_required",
        "authoritative_receipt_reconciliation",
        "unknown_blocks_restore",
    ]


async def main():
    payload = json.load(sys.stdin)
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in payload["files"].items()
    )
    base = ModuleType("harness_runtime_support")
    exec(compile(payload["support"], "runtime_probe", "exec"), base.__dict__)
    os.environ["HARNESS__IDE_ENABLED"] = "true"
    os.environ["HARNESS__IDE_COMMANDS_ENABLED"] = "true"
    async with base.disposable() as engine:
        cases = await exercise(base, engine)
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
