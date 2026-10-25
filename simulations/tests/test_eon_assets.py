"""Pinned input restoration must preserve identity and reject corrupted work copies."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
from probes.eon_assets import FILES, hydrate


@pytest.fixture
def pinned_inputs(tmp_path, monkeypatch):
    root = tmp_path
    base = root / "upstream"
    base.mkdir()
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    originals = {}
    for name in FILES:
        path = base / name
        path.parent.mkdir(exist_ok=True)
        originals[name] = ("software fixture " + name + "\n").encode()
        path.write_bytes(originals[name])
    subprocess.run(["git", "-C", str(base), "add", "--", *FILES], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(base),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    commit = (
        subprocess.check_output(["git", "-C", str(base), "rev-parse", "HEAD"])
        .decode()
        .strip()
    )
    work = root / "work"
    registry = root / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": "SIM-006",
                        "path": "upstream",
                        "commit": commit,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(inventory, "ROOT", root)
    monkeypatch.setattr(inventory, "WORK", work)
    monkeypatch.setattr(inventory, "REGISTRY", registry)
    return base, work / "SIM-006" / "run", originals


def test_restored_inputs_match_pin_and_repeat_without_source_changes(pinned_inputs):
    base, run, originals = pinned_inputs
    hydrate(run)
    manifest = (run / "pinned-assets.json").read_bytes()
    for entry in json.loads(manifest)["restored"]:
        raw = (run / "source" / entry["path"]).read_bytes()
        assert raw == originals[entry["path"]]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
    hydrate(run)
    assert (run / "pinned-assets.json").read_bytes() == manifest
    assert not subprocess.check_output(
        ["git", "-C", str(base), "status", "--porcelain"]
    )


def test_corrupted_restored_data_is_rejected_without_replacing_source(pinned_inputs):
    base, run, originals = pinned_inputs
    hydrate(run)
    (run / "source" / FILES[0]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Pinned Eon data mismatch"):
        hydrate(run)
    assert (base / FILES[0]).read_bytes() == originals[FILES[0]]
