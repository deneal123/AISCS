"""DoomFly must reuse the exact locked primary input, never a near version."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import simctl
from probes.doom_assets import prepare_inputs


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "WORK", tmp_path / "work")
    monkeypatch.setattr(simctl, "WORK", tmp_path / "work")
    run = tmp_path / "work/SIM-023/run"
    source = run / "source"
    lock = source / "data-provenance/malecns_v1/source.lock.json"
    lock.parent.mkdir(parents=True)
    raw = (
        tmp_path / "work/SIM-001/20261005T105111Z-6999dc/connectome/raw/primary.feather"
    )
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"exact registered primary data")
    url = "https://example.org/primary.feather"
    info = {
        "url": url,
        "bytes": raw.stat().st_size,
        "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
    }
    lock.write_text(json.dumps({"edges.feather": info}))
    config = source / "doom/datasets.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"datasets": {"malecns_v1": {"files": {"edges.feather": url}}}})
    )
    return run, raw, config


def test_exact_locked_input_reused_and_changed_copy_preserved(tmp_path, monkeypatch):
    run, raw, _ = fixture(tmp_path, monkeypatch)
    prepare_inputs(run)
    destination = run / "source/connectome_data/malecns_v1/edges.feather"
    assert destination.read_bytes() == raw.read_bytes()
    prepare_inputs(run)
    destination.write_bytes(b"intentional working change")
    with pytest.raises(ValueError, match="Existing DOOMFLY input differs"):
        prepare_inputs(run)
    assert destination.read_bytes() == b"intentional working change"


def test_changed_primary_hash_rejected_before_copy(tmp_path, monkeypatch):
    run, raw, _ = fixture(tmp_path, monkeypatch)
    raw.write_bytes(b"X" * raw.stat().st_size)
    with pytest.raises(ValueError, match="primary SHA-256 mismatch"):
        prepare_inputs(run)
    assert not (run / "source/connectome_data/malecns_v1/edges.feather").exists()


def test_changed_route_rejected(tmp_path, monkeypatch):
    run, _, config = fixture(tmp_path, monkeypatch)
    config.write_text(
        json.dumps(
            {
                "datasets": {
                    "malecns_v1": {
                        "files": {"edges.feather": "https://elsewhere.invalid"}
                    }
                }
            }
        )
    )
    with pytest.raises(ValueError, match="route and pinned lock disagree"):
        prepare_inputs(run)
