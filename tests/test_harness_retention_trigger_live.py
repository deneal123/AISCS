"""Full historical PostgreSQL schema, including the original BEFORE UPDATE trigger."""

import importlib.util
import io
import os
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations

from scripts.harness.live.host import run_command_probe


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_retention_trigger_migration_is_additive_and_guards_downgrade(direction):
    path = Path(__file__).parents[1] / "alembic/versions/048_retained_reservation_trigger.py"
    spec = importlib.util.spec_from_file_location("retained_trigger", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        getattr(migration, direction)()
    ddl = output.getvalue()
    assert migration.down_revision == "047_command_receipts"
    assert "DELETE" not in ddl and "ALTER TABLE" not in ddl
    if direction == "upgrade":
        assert "NEW.status = 'reserved' AND NEW.harness_task_id IS NULL" in ddl
    else:
        assert ddl.index("RAISE EXCEPTION") < ddl.index("CREATE OR REPLACE FUNCTION")


@pytest.mark.skipif(
    os.getenv("HARNESS_RETENTION_TRIGGER_LIVE") != "1", reason="isolated full schema opt-in"
)
def test_retained_hold_and_terminal_state_survive_the_actual_expiry_trigger():
    assert run_command_probe(retention=True)["retention_trigger_verified"]
