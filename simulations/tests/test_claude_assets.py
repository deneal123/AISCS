"""Known missing LFS objects must not be retried or replaced on a fresh run."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
from probes import claude_assets


def test_exact_blob_reuse_and_terminal_lfs_missing_state(tmp_path, monkeypatch):
    work = tmp_path / "work"
    primary = work / "SIM-006/primary"
    primary.mkdir(parents=True)
    con = primary / "conn.parquet"
    con.write_bytes(b"registered parquet fixture")
    comp = primary / "comp.csv"
    comp.write_bytes(b"root_id\r\n123\r\n")
    monkeypatch.setattr(claude_assets, "PARQUET", claude_assets.blob(con.read_bytes()))
    monkeypatch.setattr(
        claude_assets, "COMPLETENESS", claude_assets.blob(b"root_id\n123\n")
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "WORK", work)
    registry = tmp_path / "registry.json"
    monkeypatch.setattr(inventory, "REGISTRY", registry)
    row = {"id": "SIM-015", "commit": claude_assets.COMMIT}
    registry.write_text(json.dumps({"candidates": [row]}), encoding="utf-8")
    (work / "SIM-015").mkdir()
    preparation = {
        "connectivity_primary": con.relative_to(tmp_path).as_posix(),
        "source_completeness": comp.relative_to(tmp_path).as_posix(),
        "source_completeness_sha256": claude_assets.sha(comp),
        "pointers": [
            {
                "name": "plastic_weights.pt",
                "body": "oid sha256:" + "1" * 64 + "\nsize 7\n",
            }
        ],
    }
    (work / "SIM-015/input-routes-preparation.json").write_text(
        json.dumps(preparation), encoding="utf-8"
    )
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise OSError("primary object absent")

    monkeypatch.setattr(claude_assets.urllib.request, "urlopen", unavailable)
    first = work / "SIM-015/first"
    first.mkdir()
    claude_assets.hydrate(first)
    assert len(calls) == 2
    assert comp.read_bytes() == b"root_id\r\n123\r\n"
    assert (
        first / "source/data/2025_Completeness_783.csv"
    ).read_bytes() == b"root_id\n123\n"
    manifest = first / "claude-inputs.json"
    row["frozen_inputs"] = {
        "path": manifest.relative_to(tmp_path).as_posix(),
        "sha256": claude_assets.sha(manifest),
    }
    registry.write_text(json.dumps({"candidates": [row]}), encoding="utf-8")
    second = work / "SIM-015/second"
    second.mkdir()
    claude_assets.hydrate(second)
    assert len(calls) == 2  # No second pair of download attempts.
    receipt = json.loads((second / "claude-inputs.json").read_text())
    assert receipt["inputs"][-1]["status"] == "unavailable"
    assert not (second / "source/data/plastic_weights.pt").exists()
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest changed"):
        claude_assets.hydrate(second)
    assert len(calls) == 2


def test_blob_identity_includes_size_and_content():
    data = b"exact\n"
    assert claude_assets.blob(data) == hashlib.sha1(b"blob 6\0exact\n").hexdigest()
    assert claude_assets.blob(data) != claude_assets.blob(data.replace(b"\n", b"\r\n"))
