"""An alternate trial must retain its version and exact primary bytes."""

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import simctl
from probes import flylif_assets


@pytest.mark.parametrize("corrupt", [False, True])
def test_alternate_codex_inputs_keep_primary_identity(tmp_path, monkeypatch, corrupt):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(inventory, "WORK", tmp_path)
    monkeypatch.setattr(flylif_assets, "ROOT", tmp_path)
    monkeypatch.setattr(flylif_assets, "prepare_font", lambda _: None)
    primary = tmp_path / "SIM-010/primary"
    primary.mkdir(parents=True)
    inputs = []
    for name in flylif_assets.NAMES:
        source = primary / name
        source.write_bytes(gzip.compress(b"header\nregistered\n"))
        inputs.append(
            {
                "file": name,
                "status": "verified",
                "sha256": flylif_assets.sha(source),
                "url": "https://primary.example/783/" + name,
            }
        )
    manifest = primary / "inputs.json"
    manifest.write_text(json.dumps({"inputs": inputs}), encoding="utf-8")
    reference = {
        "path": manifest.relative_to(tmp_path).as_posix(),
        "sha256": flylif_assets.sha(manifest),
    }
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps({"candidates": [{"id": "SIM-010", "frozen_inputs": reference}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(flylif_assets, "REGISTRY", registry)
    if corrupt:
        (primary / next(iter(flylif_assets.NAMES))).write_bytes(
            gzip.compress(b"changed")
        )
    run = tmp_path / "SIM-014/run"
    run.mkdir(parents=True)
    if corrupt:
        with pytest.raises(ValueError, match="primary input changed"):
            flylif_assets.hydrate(run)
        assert not (run / "flylif-inputs.json").exists()
    else:
        flylif_assets.hydrate(run)
        receipt = json.loads((run / "flylif-inputs.json").read_text())
        assert "alternate" in receipt["materialization"]
        assert "not established" in receipt["author_graph_identity"]
        assert receipt["network_attempts"] == 0
        assert len(receipt["inputs"]) == 3
        for item in receipt["inputs"]:
            assert (run / item["derived_file"]).read_bytes() == b"header\nregistered\n"
        assert flylif_assets.sha(manifest) == reference["sha256"]
