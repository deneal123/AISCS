"""Dev-only disposable PostgreSQL runtime/hold acceptance. No model or workspace calls.

Run through the opt-in host test, which supplies source hashes on stdin. Only
closed stage/case names leave the process, never credentials or SQL diagnostics.
"""

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import asyncpg
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from service.services.billing.application.frozen_pricing import FrozenPricing
from service.services.billing.persistence.billing_repository import BillingRepository
from service.services.billing.persistence.sql import (
    _COMMIT_RESERVATION_SQL,
    _SUM_ACTIVE_RESERVATIONS_SQL,
)
from service.services.chat.application.harness_capability import HarnessOwner
from service.services.chat.persistence.harness.fee_reconciliation import reconcile_tool_fees
from service.services.chat.persistence.harness.rebind import rebind_harness
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.services.chat.persistence.harness.state import owned_row
from service.settings import config
from service.shared.harness_protocol import (
    Admission,
    CallReceipt,
    EffectIntent,
    EffectResult,
    Exchange,
    HarnessFailure,
    PaidCall,
)
from service.shared.task_contract import digest_payload

logging.disable(logging.CRITICAL)
STAGE = "source_parity"


class ProbeSession(AsyncSession):
    async def execute(self, *args, **kwargs):
        global STAGE
        try:
            return await super().execute(*args, **kwargs)
        except Exception as error:
            code = getattr(getattr(error, "orig", None), "sqlstate", None)
            if isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{5}", code):
                STAGE += ":" + code
            # Closed diagnostic tags, not the exception/SQL/parameter values.
            diagnostic = str(error)
            for marker, tag in (("expected str", "expected_text"), ("UUID", "uuid")):
                if marker in diagnostic:
                    STAGE += ":" + tag
            raise


def migrate(connection, name):
    path = Path("alembic/versions") / name
    spec = importlib.util.spec_from_file_location("probe_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        module.upgrade()


@asynccontextmanager
async def disposable():
    assert config.pg.host == "postgres"
    name = "gpthub_runtime_" + uuid4().hex[:24]
    assert re.fullmatch(r"gpthub_runtime_[a-f0-9]{24}", name)
    admin = await asyncpg.connect(
        host=config.pg.host,
        port=config.pg.port,
        user=config.pg.user,
        password=config.pg.password,
        database=config.pg.db,
        timeout=5,
    )
    engine, created = None, False
    try:
        await admin.execute('CREATE DATABASE "' + name + '"')
        created = True
        engine = create_async_engine(
            URL.create(
                "postgresql+asyncpg",
                username=config.pg.user,
                password=config.pg.password,
                host=config.pg.host,
                port=config.pg.port,
                database=name,
            )
        )
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            await admin.execute('DROP DATABASE "' + name + '" WITH (FORCE)')
        await admin.close()


async def seed(
    engine, *, project_id="probe", generation="generation", credit_limit=100, pricing_model=None
):
    owner = HarnessOwner(
        task_id=str(uuid4()),
        job_id=str(uuid4()),
        user_id=str(uuid4()),
        thread_id=str(uuid4()),
        attempt_id=str(uuid4()),
        epoch=1,
        project_id=project_id,
        generation=generation,
    )
    owner = owner.model_copy(update={"task_id": owner.job_id})
    admission = Admission(
        task_id=owner.task_id,
        project_id=owner.project_id,
        generation=owner.generation,
        surface="ide",
        goal="PRIVATE_PROBE",
        source_revision="r1",
        actions=["read", "write", "exec"],
        credit_limit=credit_limit,
        pricing_model=pricing_model,
        reservation_id=str(uuid4()),
    )
    payload = {
        "thread_id": owner.thread_id,
        "_execution_attempt_v1": owner.attempt_id,
        "_execution_accounting_v1": {"reservation_id": admission.reservation_id},
    }
    async with engine.begin() as db:
        for sql in (
            "CREATE SCHEMA profile",
            'CREATE TABLE profile."user" (id uuid PRIMARY KEY)',
            "CREATE TABLE profile.chat_threads (thread_id uuid PRIMARY KEY,user_id uuid)",
            "CREATE TABLE profile.user_launch (id uuid PRIMARY KEY,user_id uuid,type text,"
            "status text,payload jsonb,updated_at timestamptz DEFAULT now())",
            "CREATE TABLE profile.token_reservations (reservation_id uuid PRIMARY KEY,"
            "user_id uuid,tokens_reserved bigint,expires_at timestamptz,status text,"
            "committed_at timestamptz,refunded_at timestamptz)",
            "CREATE TABLE profile.human_question (source_job_id uuid,resume_job_id uuid,"
            "user_id uuid,thread_id uuid,state text)",
        ):
            await db.execute(text(sql))
        for name in (
            "043_harness_state.py",
            "044_harness_runtime.py",
            "045_harness_reservation_retention.py",
        ):
            await db.run_sync(lambda connection, name=name: migrate(connection, name))
        params = owner.params()
        await db.execute(text('INSERT INTO profile."user" VALUES (:user_id)'), params)
        await db.execute(
            text("INSERT INTO profile.chat_threads VALUES (:thread_id,:user_id)"), params
        )
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:job_id,:user_id,'CHAT','PROCESSING',CAST(:payload AS jsonb))"
            ),
            {**params, "payload": json.dumps(payload)},
        )
        await db.execute(
            text(
                "INSERT INTO profile.token_reservations VALUES "
                "(:id,:owner,:amount,now()+interval '1 hour','reserved',NULL,NULL,NULL)"
            ),
            {
                "id": UUID(admission.reservation_id),
                "owner": params["user_id"],
                "amount": credit_limit,
            },
        )
    return owner, admission


async def handoff(factory, connector, repo, owner, admission):
    global STAGE
    STAGE = "handoff_checkpoint"
    current = await repo.exchange(owner, Exchange(opcode="state"))
    state = current["snapshot"]["state"]
    state.update(rounds=15, repairs=1)
    await repo.exchange(
        owner,
        Exchange(
            opcode="checkpoint",
            expected_revision=current["snapshot"]["revision"],
            state=state,
            continuation={
                "agent_name": "general",
                "phase": "model",
                "provider": {
                    "provider": "gigachat",
                    "model": "test-model",
                },
                "messages": [{"role": "user", "content": "PRIVATE_GOAL"}],
            },
        ),
    )
    child = owner.model_copy(update={"job_id": str(uuid4()), "attempt_id": str(uuid4())})
    reservation = uuid4()
    STAGE = "handoff_fixture"
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO profile.user_launch(id,user_id,type,status,payload) "
                "VALUES (:job_id,:user_id,'CHAT','PROCESSING',CAST(:body AS jsonb))"
            ),
            {
                **child.params(),
                "body": json.dumps(
                    {"_execution_attempt_v1": child.attempt_id, "thread_id": child.thread_id}
                ),
            },
        )
        await db.execute(
            text(
                "INSERT INTO profile.human_question VALUES "
                "(:parent,:job_id,:user_id,:thread_id,'accepted')"
            ),
            {**child.params(), "parent": UUID(owner.job_id)},
        )
        await db.execute(
            text(
                "INSERT INTO profile.token_reservations VALUES "
                "(:id,:owner,100,now()+interval '1 hour','reserved',NULL,NULL,NULL)"
            ),
            {"id": reservation, "owner": UUID(owner.user_id)},
        )
        await db.commit()
    STAGE = "handoff_rebind"
    bound = await rebind_harness(
        connector, child, reservation_id=str(reservation), parent_id=UUID(owner.job_id)
    )
    STAGE = "handoff_readback"
    restored = (await repo.exchange(bound, Exchange(opcode="state")))["snapshot"]
    assert restored["state"]["rounds"] == 15 and restored["state"]["repairs"] == 1
    assert restored["state"]["contract"] == state["contract"]
    assert restored["continuation"]["provider"]["provider"] == "gigachat"
    assert restored["spent_credits"] == 10 and restored["admission"]["credit_limit"] == 100
    try:
        await repo.exchange(owner, Exchange(opcode="state"))
    except HarnessFailure as error:
        assert error.code == "harness_fenced"
    else:
        raise AssertionError("old job retained authority")
    uncertain = PaidCall(
        operation_id=str(uuid4()),
        provider="gigachat",
        model="test-model",
        prompt=10,
        completion=10,
        request_digest="0" * 64,
        kind="chat",
    )
    await repo.exchange(bound, Exchange(opcode="grant", call=uncertain))
    await repo.exchange(bound, Exchange(opcode="dispatch", operation_id=uncertain.operation_id))
    await repo.exchange(
        bound,
        Exchange(
            opcode="call_receipt",
            receipt=CallReceipt(
                operation_id=uncertain.operation_id,
                status="unknown",
            ),
        ),
    )
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.user_launch SET payload=payload || "
                "jsonb_build_object('_cancel_requested_v1',true) WHERE id=:job"
            ),
            {"job": UUID(bound.job_id)},
        )
        await db.commit()
    try:
        await repo.exchange(bound, Exchange(opcode="dispatch_effect", operation_id=str(uuid4())))
    except HarnessFailure as error:
        assert error.code == "cancelled"
    else:
        raise AssertionError("stopped task dispatched")
    async with factory() as db:
        await db.execute(
            text(
                "UPDATE profile.token_reservations SET expires_at=now()-interval '1 hour' "
                "WHERE reservation_id=:id"
            ),
            {"id": reservation},
        )
        await db.commit()
    assert await BillingRepository(connector).cleanup_expired_reservations() == 0
    after_stop = (await repo.exchange(bound, Exchange(opcode="state")))["snapshot"]
    assert after_stop["held_credits"] > 0
    async with factory() as db:
        assert (
            await db.scalar(text(_SUM_ACTIVE_RESERVATIONS_SQL), {"user_id": owner.user_id}) == 100
        )


async def exercise(engine):
    global STAGE
    STAGE = "fixture"
    owner, admission = await seed(engine)
    factory = async_sessionmaker(engine, class_=ProbeSession, expire_on_commit=False)
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
        surcharges={"workspace_tool": "0.1"},
    )
    STAGE = "admission"
    await repo.admit(owner, admission, tariff)
    STAGE = "seal"
    await repo.exchange(
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
    intent = EffectIntent(
        operation_id=str(uuid4()),
        name="ide_write_file",
        action="write",
        arguments='{"path":"a.py"}',
        source_revision="r1",
    )
    fee = PaidCall(
        operation_id=str(uuid5(UUID(intent.operation_id), "billing")),
        provider="local",
        model="workspace_tool",
        prompt=0,
        completion=0,
        kind="tool",
        billing_tool="workspace_tool",
        request_digest=digest_payload(intent.model_dump(mode="json")),
    )
    STAGE = "effect_receipt"
    for request in (
        Exchange(opcode="prepare_effect", effect=intent),
        Exchange(opcode="grant", call=fee),
        Exchange(opcode="dispatch", operation_id=fee.operation_id),
        Exchange(opcode="dispatch_effect", operation_id=intent.operation_id),
        Exchange(
            opcode="effect_receipt",
            effect_result=EffectResult(
                operation_id=intent.operation_id,
                status="succeeded",
                text="PRIVATE_RESULT",
                charged=True,
            ),
        ),
    ):
        await repo.exchange(owner, request)

    async def reconcile():
        async with factory() as db:
            await owned_row(db, owner)
            count = await reconcile_tool_fees(db, UUID(owner.task_id))
            await db.commit()
            return count

    STAGE = "fee_race"
    assert sorted(await asyncio.gather(reconcile(), reconcile())) == [0, 1]
    assert await reconcile() == 0
    status = await repo.exchange(
        owner,
        Exchange(opcode="operation_status", operation_id=fee.operation_id, operation_kind="paid"),
    )
    assert status["operation_status"]["status"] == "succeeded"
    result = await repo.exchange(owner, Exchange(opcode="result"))
    assert result["result"]["status"] != "completed"
    STAGE = "ttl"
    billing = BillingRepository(connector)
    async with factory() as db:
        await db.execute(
            text("UPDATE profile.token_reservations SET expires_at=now()-interval '1 hour'")
        )
        await db.commit()
    assert await billing.cleanup_expired_reservations() == 0
    await billing.release_reservation(
        user_id=owner.user_id, reservation_id=admission.reservation_id
    )
    async with factory() as db:
        assert (
            await db.scalar(text(_SUM_ACTIVE_RESERVATIONS_SQL), {"user_id": owner.user_id}) == 100
        )
    try:
        await repo.exchange(owner, Exchange(opcode="grant", call=fee))
    except HarnessFailure as error:
        assert error.code == "budget_unavailable"
    else:
        raise AssertionError("expired hold authorized dispatch")
    STAGE = "hold_close"
    async with factory() as db:
        args = {"rid": admission.reservation_id, "user_id": owner.user_id}
        first = await db.execute(text(_COMMIT_RESERVATION_SQL), args)
        second = await db.execute(text(_COMMIT_RESERVATION_SQL), args)
        assert first.rowcount == 1 and second.rowcount == 0
        await db.commit()
    STAGE = "handoff"
    await handoff(factory, connector, repo, owner, admission)
    return [
        "runtime_admission",
        "committed_tool_fee_race",
        "ttl_hold_retention",
        "expired_dispatch_denied",
        "hold_close_once",
        "human_question_state_and_fence",
        "stop_blocks_dispatch",
        "unknown_cost_survives_stop_ttl",
    ]


async def main():
    global STAGE
    files = json.load(sys.stdin)["files"]
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        for path, digest in files.items()
    )
    os.environ["HARNESS__IDE_ENABLED"] = "true"  # this probe process only, not the running backend
    async with disposable() as engine:
        cases = await exercise(engine)
    print(json.dumps({"cases": cases, "fixture_removed": True, "source_parity": True}))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(json.dumps({"failed_stage": STAGE}))
        raise SystemExit(1) from None
