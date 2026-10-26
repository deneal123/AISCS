"""Cleanup must not be the only surviving reference to native-test figures."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import retain_visuals


def test_preserve_visual_bytes_and_resist_changed_output(tmp_path, monkeypatch):
    monkeypatch.setattr(retain_visuals, "WORK", tmp_path)
    monkeypatch.setattr(inventory, "WORK", tmp_path)
    run = tmp_path / "SIM-021/run"
    source = run / "tmp/test-output"
    source.mkdir(parents=True)
    (run / "result.json").write_text(json.dumps({"status": "reproduced"}))
    original = source / "plot.png"
    original.write_bytes(b"test visual bytes")
    (source / "cache.bin").write_bytes(b"discardable")
    items = retain_visuals.retain(run, "tmp/test-output")
    assert len(items) == 1
    assert (run / items[0]["retained"]).read_bytes() == original.read_bytes()
    assert retain_visuals.retain(run, "tmp/test-output") == items
    original.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        retain_visuals.retain(run, "tmp/test-output")
    assert (run / items[0]["retained"]).read_bytes() == b"test visual bytes"
    with pytest.raises(ValueError, match="inside the run"):
        retain_visuals.retain(run, "../../outside")
