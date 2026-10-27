"""Offline SQL predicate checks; not PostgreSQL locking or live acceptance.

SQLite executes the actual billing predicates with only UUID casts adapted.
No external database, service, model or migration is started by these tests.
"""

import importlib.util
import io
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from service.services.billing.persistence import sql
from service.services.chat.persistence.harness.reservations import require_reconciled_cost, retain
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.shared.harness_protocol import HarnessFailure, Snapshot
from tests.test_harness_runtime_contract import admission


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.execute("ATTACH DATABASE ':memory:' AS profile")
    connection.create_function("now", 0, lambda: 100)
    connection.execute(
        "CREATE TABLE profile.token_reservations (reservation_id TEXT PRIMARY KEY, "
        "user_id TEXT, tokens_reserved INTEGER, expires_at INTEGER, status TEXT, "
        "harness_task_id TEXT, committed_at INTEGER, refunded_at INTEGER)"
    )
    yield connection
    connection.close()


def execute(db, statement, params=None):
    statement = re.sub(r"CAST\((:\w+) AS uuid\)", r"\1", statement)
    return db.execute(statement, params or {})


def insert(db, *, retained=True, expired=True, status="reserved", owner="owner"):
    db.execute(
        "INSERT INTO profile.token_reservations VALUES ('hold', ?, 70, ?, ?, ?, NULL, NULL)",
        (owner, 99 if expired else 101, status, "task" if retained else None),
    )


@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("retained", [False, True])
def test_retained_obligation_remains_in_available_balance_after_ttl(db, expired, retained):
    insert(db, retained=retained, expired=expired)
    total = execute(db, sql._SUM_ACTIVE_RESERVATIONS_SQL, {"user_id": "owner"}).fetchone()[0]
    assert total == (70 if retained or not expired else 0)
    assert execute(db, sql._SUM_ACTIVE_RESERVATIONS_SQL, {"user_id": "other"}).fetchone()[0] == 0


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_cleanup_releases_only_expired_unretained_money(db, retained, expired):
    insert(db, retained=retained, expired=expired)
    removed = execute(db, sql._CLEANUP_EXPIRED_RESERVATIONS_SQL).fetchall()
    assert len(removed) == int(expired and not retained)
    assert execute(db, sql._CLEANUP_EXPIRED_RESERVATIONS_SQL).fetchall() == []


@pytest.mark.parametrize("status", ["reserved", "committed", "refunded"])
def test_generic_release_cannot_erase_harness_obligation(db, status):
    insert(db, status=status)
    for _ in range(2):
        execute(db, sql._OWNED_RELEASE_RESERVATION_SQL, {"rid": "hold", "user_id": "owner"})
    assert db.execute("SELECT status FROM profile.token_reservations").fetchone()[0] == status


def test_confirmed_settlement_closes_retained_hold_once(db):
    insert(db)
    args = {"rid": "hold", "user_id": "owner"}
    assert execute(db, sql._COMMIT_RESERVATION_SQL, {**args, "user_id": "other"}).rowcount == 0
    assert execute(db, sql._COMMIT_RESERVATION_SQL, args).rowcount == 1
    assert execute(db, sql._COMMIT_RESERVATION_SQL, args).rowcount == 0
    assert execute(db, sql._SUM_ACTIVE_RESERVATIONS_SQL, args).fetchone()[0] == 0


def test_snapshot_distinguishes_retained_obligation_from_expired_cleanup_candidate(db):
    insert(db)
    assert execute(db, sql._RESERVATION_SNAPSHOT_SQL).fetchone() == (1, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_admission_retains_only_exact_owned_active_reservation(accepted):
    task, owner, reservation = uuid4(), uuid4(), uuid4()
    session = SimpleNamespace(scalar=AsyncMock(return_value=reservation if accepted else None))
    args = dict(task_id=task, user_id=owner, reservation_id=reservation, credits=70)
    if accepted:
        await retain(session, **args)
    else:
        with pytest.raises(HarnessFailure, match="budget_unavailable"):
            await retain(session, **args)
    statement, params = session.scalar.call_args.args
    assert params == {"task": task, "owner": owner, "reservation": reservation, "credits": 70}
    assert "status='reserved'" in str(statement) and "expires_at>now()" in str(statement)
    assert "harness_task_id IS NULL OR harness_task_id=:task" in str(statement)


@pytest.mark.asyncio
async def test_retention_is_not_permission_to_dispatch_after_expiry():
    current = Snapshot(admission=admission())
    session = SimpleNamespace(scalar=AsyncMock(return_value=False))
    with pytest.raises(HarnessFailure, match="budget_unavailable"):
        await HarnessRuntimeRepository._funds(session, current)
    statement, params = session.scalar.call_args.args
    assert "harness_task_id=:task" in str(statement) and "expires_at>now()" in str(statement)
    assert str(params["task"]) == current.admission.task_id


@pytest.mark.asyncio
async def test_human_answer_cannot_rebind_a_dispatched_unacknowledged_paid_call():
    session = SimpleNamespace(scalar=AsyncMock(return_value=True))
    with pytest.raises(HarnessFailure, match="cost_unknown"):
        await require_reconciled_cost(session, uuid4())
    statement = str(session.scalar.call_args.args[0])
    assert "'dispatched','unknown'" in statement


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_retention_migration_compiles_offline_without_losing_obligations(direction):
    path = Path(__file__).parents[1] / "alembic/versions/045_harness_reservation_retention.py"
    spec = importlib.util.spec_from_file_location("harness_retention_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    ddl = output.getvalue()
    assert migration.down_revision == "044_harness_runtime"
    assert len(migration.revision) <= 32
    if direction == "upgrade":
        assert "ADD COLUMN harness_task_id UUID" in ddl
        assert "FROM profile.harness_task" in ddl and "r.status='reserved'" in ddl
        assert "DELETE" not in ddl and "expires_at" not in ddl
    else:
        assert ddl.index("RAISE EXCEPTION") < ddl.index("DROP COLUMN")
