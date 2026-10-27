"""Explicit opt-in: disposable database, real repository, no model or workspace."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.getenv("HARNESS_JOURNAL_LIVE") != "1", reason="disposable PG journal opt-in")
def test_harness_journal_concurrency_replay_fences_and_unknown_commit():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "alembic/versions/043_harness_state.py",
        "service/shared/task_contract.py",
        "service/services/chat/domain/harness_state.py",
        "service/services/chat/persistence/harness/journal.py",
    ]
    files = {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}
    probe = (root / "scripts/probe_harness_journal.py").read_text(encoding="utf-8")
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
        pytest.fail("harness_probe_output_invalid")
    assert result.returncode == 0, f"harness_journal_probe_failed:{outcome}"
    assert outcome == {
        "cases": [
            "create_replay_fences",
            "checkpoint_cas_lost_ack",
            "intent_dispatch_race",
            "unknown_effect_blocks_followup",
            "reconciliation_receipt_before_evidence",
            "dispatch_commit_loss_no_repeat",
            "stop_fence_keeps_reconciliation",
            "migration_roundtrip",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
