"""Opt-in real PostgreSQL runtime/retention; no paid provider or workspace mutation."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("HARNESS_RUNTIME_LIVE") != "1", reason="disposable runtime PG opt-in")
def test_runtime_retention_and_fee_reconciliation_on_postgres():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "alembic/versions/043_harness_state.py",
        "alembic/versions/044_harness_runtime.py",
        "alembic/versions/045_harness_reservation_retention.py",
        "service/shared/harness_protocol.py",
        "service/shared/task_contract.py",
        "service/services/chat/persistence/harness/runtime.py",
        "service/services/chat/persistence/harness/state.py",
        "service/services/chat/persistence/harness/fee_reconciliation.py",
        "service/services/chat/persistence/harness/reservations.py",
        "service/services/billing/persistence/sql.py",
    ]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    probe = (root / "scripts/harness/runtime.py").read_text(encoding="utf-8")
    result = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", probe],
        input=json.dumps({"files": files}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    try:
        outcome = json.loads(result.stdout)
    except ValueError:
        pytest.fail("harness_runtime_probe_output_invalid")
    assert result.returncode == 0, f"harness_runtime_probe_failed:{outcome}"
    assert outcome == {
        "cases": [
            "runtime_admission",
            "committed_tool_fee_race",
            "ttl_hold_retention",
            "expired_dispatch_denied",
            "hold_close_once",
            "human_question_state_and_fence",
            "stop_blocks_dispatch",
            "unknown_cost_survives_stop_ttl",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
