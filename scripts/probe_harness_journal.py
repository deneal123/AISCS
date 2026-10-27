"""Disposable PostgreSQL acceptance for the journal (not command/PDF E2E).

Executed by the opt-in test inside the dev backend. Never prints DSNs, SQL
exceptions, private checkpoints, prompts or receipts. No dev schema migration.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import re
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.services.chat.domain.harness_state import (
    HarnessCheckpoint,
    OperationIntent,
    OperationReceipt,
)
from service.services.chat.persistence.harness.journal import HarnessRepository, HarnessScope
from service.settings import config
from service.shared.repositories.exceptions import RepositoryOperationalError
from service.shared.task_contract import TaskEvidence, TaskState

logging.disable(logging.CRITICAL)
STAGE = "source_parity"


class AckSession(AsyncSession):
    async def execute(self, *args, **kwargs):
        global STAGE
        try:
            return await super().execute(*args, **kwargs)
        except Exception as error:
            STAGE += ":" + type(error).__name__
            original = getattr(error, "orig", None)
            code = getattr(original, "sqlstate", None)
            if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
                STAGE += ":" + code
            raise

    async def commit(self):
        lose = self.info.pop("lose_ack", False)
        await super().commit()
        if lose:
            raise OperationalError("private", {}, Exception("private"))


def migration(connection, *, down=False):
    path = Path("alembic/versions/043_harness_state.py")
    spec = importlib.util.spec_from_file_location("harness_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.downgrade() if down else module.upgrade()


async def main():
    global STAGE
    sources = json.load(sys.stdin)["files"]
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in sources.items()
    )
    assert config.pg.host == "postgres"
    database = "gpthub_harness_" + uuid4().hex[:24]
    assert re.fullmatch(r"gpthub_harness_[0-9a-f]{24}", database)
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database=config.pg.db,
        timeout=5,
    )
    engine = None
    created = False
    cases = []
    try:
        STAGE = "fixture"
        await admin.execute('CREATE DATABASE "' + database + '"')
        created = True
        engine = create_async_engine(
            URL.create(
                "postgresql+asyncpg",
                username=config.pg.user,
                password=config.pg.password,
                host=config.pg.host,
                port=config.pg.port,
                database=database,
            )
        )
        async with engine.begin() as db:
            await db.execute(text("CREATE SCHEMA profile"))
            await db.execute(text('CREATE TABLE profile."user" (id uuid PRIMARY KEY)'))
            await db.execute(
                text("CREATE TABLE profile.chat_threads (thread_id uuid PRIMARY KEY,user_id uuid)")
            )
            await db.execute(
                text(
                    "CREATE TABLE profile.user_launch "
                    "(id uuid PRIMARY KEY,user_id uuid,type text,status text,payload jsonb)"
                )
            )
            await db.run_sync(migration)
        factory = async_sessionmaker(engine, class_=AckSession, expire_on_commit=False)
        ack = {"next": False}

        @asynccontextmanager
        async def context():
            async with factory() as db:
                db.info["lose_ack"] = ack["next"]
                ack["next"] = False
                yield db

        connector = SimpleNamespace(get_session_context=context)
        repository = HarnessRepository(connector)
        scope = HarnessScope(uuid4(), uuid4(), uuid4(), uuid4(), "project", "generation")
        checkpoint = HarnessCheckpoint(
            state=TaskState.model_validate(
                {
                    "contract": {
                        "task_id": str(scope.job_id),
                        "project_id": scope.project_id,
                        "generation": scope.generation,
                        "kind": "change",
                        "goal": "PRIVATE_GOAL",
                        "actions": ["read", "write", "exec"],
                        "credit_limit": 100,
                        "criteria": [
                            {"criterion_id": "source", "kind": "file", "target": "src/a.py"}
                        ],
                    },
                    "source_revision": "r1",
                }
            )
        )
        async with engine.begin() as db:
            await db.execute(
                text('INSERT INTO profile."user" VALUES (:owner)'), {"owner": scope.user_id}
            )
            await db.execute(
                text("INSERT INTO profile.chat_threads VALUES (:thread,:owner)"),
                {"thread": scope.thread_id, "owner": scope.user_id},
            )
            await db.execute(
                text(
                    "INSERT INTO profile.user_launch VALUES "
                    "(:job,:owner,'CHAT','PROCESSING',CAST(:body AS jsonb))"
                ),
                {
                    "job": scope.job_id,
                    "owner": scope.user_id,
                    "body": json.dumps(
                        {
                            "thread_id": str(scope.thread_id),
                            "_execution_attempt_v1": str(scope.attempt_id),
                        }
                    ),
                },
            )

        STAGE = "create_replay_fences"
        assert await repository.create(scope, checkpoint) == checkpoint
        assert await repository.create(scope, checkpoint) == checkpoint
        for patch in [
            {"user_id": uuid4()},
            {"thread_id": uuid4()},
            {"attempt_id": uuid4()},
            {"project_id": "foreign"},
            {"generation": "expired"},
        ]:
            assert await repository.read(replace(scope, **patch)) is None
        cases.append(STAGE)

        STAGE = "checkpoint_cas_lost_ack"
        advanced = HarnessCheckpoint(state=checkpoint.state.claim_round())
        ack["next"] = True
        try:
            await repository.checkpoint(scope, advanced)
            raise AssertionError("lost_ack_expected")
        except RepositoryOperationalError:
            pass
        repository = HarnessRepository(connector)  # no in-memory journal/cache survives
        assert await repository.read(scope) == advanced
        assert await repository.checkpoint(scope, advanced)
        assert not await repository.checkpoint(
            scope, HarnessCheckpoint(state=checkpoint.state.advance(repairs=1))
        )
        cases.append(STAGE)

        STAGE = "intent_dispatch_race"
        intent = OperationIntent(
            operation_id=str(uuid4()),
            kind="tool",
            action="write",
            name="ide_write_file",
            request_digest="a" * 64,
            source_revision="r1",
            criterion_ids=["source"],
        )
        assert await repository.prepare(scope, intent)
        assert await repository.prepare(scope, intent)
        different = OperationIntent.model_validate(
            {**intent.model_dump(), "request_digest": "b" * 64}
        )
        assert not await repository.prepare(scope, different)
        results = await asyncio.gather(
            repository.dispatch(scope, intent), repository.dispatch(scope, intent)
        )
        assert sorted(results) == [False, True]
        assert (await repository.operation_status(scope, intent))["status"] == "dispatched"
        assert (await repository.completion(scope))["blocker"] == "operation_unknown"
        cases.append(STAGE)

        STAGE = "unknown_effect_blocks_followup"
        unknown = OperationReceipt(status="unknown")
        assert await repository.receipt(scope, intent, unknown)
        another = OperationIntent.model_validate(
            {**intent.model_dump(), "operation_id": str(uuid4())}
        )
        assert not await repository.prepare(scope, another)
        assert not await repository.dispatch(scope, intent)
        cases.append(STAGE)

        STAGE = "reconciliation_receipt_before_evidence"
        evidence = TaskEvidence(
            criterion_id="source",
            operation_id=intent.operation_id,
            kind="file",
            target="src/a.py",
            source_revision="r2",
            digest="c" * 64,
            outcome="passed",
        )
        completed = HarnessCheckpoint(
            state=advanced.state.advance(source_revision="r2", evidence=[evidence])
        )
        assert not await repository.checkpoint(scope, completed)
        receipt = OperationReceipt(status="succeeded", result_revision="r2", evidence=[evidence])
        assert not await repository.receipt(scope, intent, receipt)
        assert await repository.receipt(scope, intent, receipt, reconciled=True)
        assert await repository.receipt(scope, intent, receipt)  # exact receipt redelivery
        assert not await repository.receipt(scope, intent, unknown, reconciled=True)
        assert await repository.checkpoint(scope, completed)
        assert (await repository.completion(scope))["status"] == "completed"
        cases.append(STAGE)

        STAGE = "dispatch_commit_loss_no_repeat"
        second = OperationIntent.model_validate({**another.model_dump(), "source_revision": "r2"})
        assert await repository.prepare(scope, second)
        ack["next"] = True
        try:
            await repository.dispatch(scope, second)
            raise AssertionError("lost_ack_expected")
        except RepositoryOperationalError:
            pass
        assert not await repository.dispatch(scope, second)
        assert (await repository.operation_status(scope, second))["status"] == "dispatched"
        assert (await repository.completion(scope))["status"] == "partial"
        cases.append(STAGE)

        STAGE = "stop_fence_keeps_reconciliation"
        async with engine.begin() as db:
            await db.execute(
                text(
                    "UPDATE profile.user_launch SET payload=jsonb_set("
                    "payload,'{_cancel_requested_v1}','true'::jsonb) WHERE id=:job"
                ),
                {"job": scope.job_id},
            )
        assert not await repository.dispatch(scope, second)
        assert not await repository.prepare(scope, another)
        assert not await repository.checkpoint(
            scope, HarnessCheckpoint(state=completed.state.claim_round())
        )
        assert await repository.receipt(scope, second, OperationReceipt(status="failed"))
        assert await repository.operation_status(scope, second)
        assert (await repository.completion(scope))["status"] == "cancelled"
        cases.append(STAGE)

        STAGE = "migration_roundtrip"
        async with engine.begin() as db:
            await db.run_sync(lambda connection: migration(connection, down=True))
            assert await db.scalar(text("SELECT to_regclass('profile.harness_task')")) is None
            await db.run_sync(migration)
            assert await db.scalar(text("SELECT count(*) FROM profile.harness_task")) == 0
        cases.append(STAGE)
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            await admin.execute('DROP DATABASE "' + database + '"')
        await admin.close()
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except BaseException as error:
        print(json.dumps({"status": "failed", "stage": STAGE, "error": type(error).__name__}))
        raise SystemExit(1) from None
