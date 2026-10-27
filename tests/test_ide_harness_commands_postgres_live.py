"""Opt-in command journal acceptance; actual command execution is not simulated."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("IDE_COMMAND_JOURNAL_LIVE") != "1", reason="disposable command PG opt-in"
)
def test_command_journal_and_checkpoint_pins_on_postgres():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "alembic/versions/046_ide_command_operations.py",
        "alembic/versions/047_command_receipt_boundaries.py",
        "service/services/chat/domain/ide/commands.py",
        "service/services/chat/application/harness_capability.py",
        "service/services/chat/persistence/harness/commands/repository.py",
        "service/services/chat/persistence/harness/commands/state.py",
        "service/services/chat/persistence/harness/commands/pins.py",
        "service/services/chat/persistence/harness/commands/gate.py",
        "service/services/chat/persistence/harness/effects.py",
        "service/services/chat/persistence/harness/runtime.py",
        "service/services/chat/persistence/harness/state.py",
        "service/services/chat/persistence/harness/reservations.py",
        "service/services/chat/persistence/ide/checkpoints/restore.py",
        "service/services/chat/persistence/ide/checkpoints/retention.py",
    ]
    payload = {
        "files": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths},
        "support": (root / "scripts/harness/runtime.py").read_text(encoding="utf-8"),
    }
    probe = (root / "scripts/harness/commands.py").read_text(encoding="utf-8")
    process = subprocess.run(
        ["docker", "exec", "-i", "gpthub-dev-backend-1", "python", "-c", probe],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    try:
        result = json.loads(process.stdout)
    except ValueError:
        pytest.fail("command_journal_probe_output_invalid")
    assert process.returncode == 0, f"command_journal_probe_failed:{result}"
    assert result == {
        "cases": [
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
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
