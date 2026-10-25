"""Reporting must not invent successful checks or publish unrelated outputs."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import checks
import publish_artifacts
from paths import REGISTRY, TODO
from report_views import render


def test_report_deterministic_and_contains_exactly_registered_checklists():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    first, second = render(registry), render(registry)
    assert first == second
    lines = first[TODO].splitlines()
    assert len([line for line in lines if line.startswith("- **[SIM-")]) == 32
    assert all(line.startswith(("# ", "- **[", "  - [")) or not line for line in lines)
    assert len([line for line in lines if line.startswith("  - [")]) == 32 * len(
        checks.LABELS
    )


def test_historical_memory_refusal_is_pending():
    row = {
        "id": "SIM-TEST",
        "evaluation": {
            "phases": [
                {
                    "stage": "functional",
                    "status": "blocked",
                    "reason": "host_memory_reserve",
                }
            ]
        },
    }
    result = {item["id"]: item for item in checks.checklist(row)}
    assert result["functional"]["status"] == "pending"
    assert result["review"]["status"] == "pending"


def test_repeated_failed_trial_does_not_prove_reproducibility():
    assert not checks.contains_repeat_proof(
        {"repeat_seed_equal": True, "status": "failed"}
    )


@pytest.mark.parametrize(
    "name", ["../escape.png", "sub\\escape.png", "/tmp/escape.png", "raw.npz"]
)
def test_publisher_rejects_unsafe_or_nonvisual_destinations(name):
    with pytest.raises(ValueError):
        publish_artifacts.locations({"id": "SIM-001"}, {"file": name})


def test_publisher_rejects_changed_source(tmp_path, monkeypatch):
    monkeypatch.setattr(publish_artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(publish_artifacts, "WORK", tmp_path / "work")
    source = tmp_path / "work/SIM-001/run/plot.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed source"):
        publish_artifacts.locations(
            {"id": "SIM-001"},
            {
                "file": "plot.png",
                "source": "work/SIM-001/run/plot.png",
                "sha256": "0" * 64,
            },
        )
