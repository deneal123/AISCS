"""047 repository checks with synthetic receipts, not executor or worker E2E."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.getenv("IDE_COMMAND_JOURNAL_LIVE") != "1", reason="disposable verification PG opt-in"
)
def test_verification_recipes_evidence_and_repair_limits_on_postgres():
    root = Path(__file__).resolve().parents[1]
    paths = [
        "alembic/versions/047_command_receipt_boundaries.py",
        "service/services/chat/persistence/harness/commands/repository.py",
        "service/services/chat/persistence/harness/commands/recipes.py",
        "service/services/chat/persistence/harness/commands/replay_guard.py",
        "service/services/chat/persistence/harness/commands/completion.py",
        "service/services/chat/persistence/harness/commands/evidence.py",
        "service/services/chat/domain/ide/verification.py",
    ]
    payload = {
        "files": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths},
        "runtime": (root / "scripts/harness/runtime.py").read_text(encoding="utf-8"),
        "commands": (root / "scripts/harness/commands.py").read_text(encoding="utf-8"),
    }
    process = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "gpthub-dev-backend-1",
            "python",
            "-c",
            (root / "scripts/harness/verification.py").read_text(encoding="utf-8"),
        ],
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
        pytest.fail("verification_probe_output_invalid", pytrace=False)
    if process.returncode != 0:
        pytest.fail(f"verification_probe_failed:{result}", pytrace=False)
    assert result == {
        "cases": [
            "verified_receipt_persists",
            "recipe_immutable_across_operations",
            "known_recipe_refusal_does_not_block_followup",
            "failure_replaces_same_revision_pass",
            "two_repairs_survive_repository_recreation",
            "command_json_size_guard",
            "command_json_state_guard",
            "blocked_verification_no_command_repeat",
        ],
        "fixture_removed": True,
        "source_parity": True,
    }
