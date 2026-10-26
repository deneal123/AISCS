"""Unavailable or inauthentic inputs must not become qualified connectomes."""

import gzip
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes import infinite_sugar_assets, optic_lobe_assets


@pytest.mark.parametrize(
    "body",
    [
        b"<html>login required</html>",
        gzip.compress(b"root_id\n1\n"),
        gzip.compress(b"root_id\n1\n")[:-4],
    ],
)
def test_invalid_or_replaced_input_is_rejected_after_two_attempts(
    tmp_path, monkeypatch, body
):
    # Use the actual pinned registration; the second case has a valid CSV header
    # but contradicts its author-supplied MD5 checksum.
    source = (
        Path(__file__).resolve().parents[1]
        / "sidecars/hsseung--OpticLobe.jl/src/codexdependencies.jl"
    )
    target = tmp_path / "source/src/codexdependencies.jl"
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    monkeypatch.setattr(infinite_sugar_assets, "hydrate", lambda *args, **kwargs: None)
    monkeypatch.setattr(optic_lobe_assets, "prepare_font", lambda run: None)
    monkeypatch.setattr(
        optic_lobe_assets, "load", lambda path: {"candidates": [{"id": "SIM-010"}]}
    )
    monkeypatch.setattr("inventory.WORK", tmp_path)
    attempts = []

    def response(req, **kwargs):
        attempts.append(req.full_url)
        stream = io.BytesIO(body)
        stream.headers = {}
        return stream

    monkeypatch.setattr(optic_lobe_assets.urllib.request, "urlopen", response)
    with pytest.raises(ValueError, match="Pinned Codex input unavailable"):
        optic_lobe_assets.hydrate(tmp_path)
    assert len(attempts) == 2
    assert not list((tmp_path / "data").rglob("*.gz"))
    assert not list((tmp_path / "data").rglob("*.partial"))


def test_frozen_input_reuse_preserves_bytes_and_date_and_rejects_tampering(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(optic_lobe_assets, "ROOT", tmp_path)
    monkeypatch.setattr("inventory.WORK", tmp_path / "work")
    monkeypatch.setattr("simctl.WORK", tmp_path / "work")
    old, new = tmp_path / "work/SIM-010/old", tmp_path / "work/SIM-010/new"
    source = old / "data/Codex neurons/neurons.csv.gz"
    source.parent.mkdir(parents=True)
    body = gzip.compress(b"root_id\n720575940599333574\n")
    source.write_bytes(body)
    receipt = {
        "date": "2026-10-25T14:21:00Z",
        "inputs": [
            {
                "file": "data/Codex neurons/neurons.csv.gz",
                "status": "verified",
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        ],
    }
    manifest = old / "inputs.json"
    manifest.write_text(json.dumps(receipt), encoding="utf-8")
    reference = {
        "path": manifest.relative_to(tmp_path).as_posix(),
        "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    files = {receipt["inputs"][0]["file"]}
    optic_lobe_assets.reuse_inputs(new, reference, files)
    assert (new / next(iter(files))).read_bytes() == body
    reused = json.loads((new / "codex-inputs.json").read_text())
    assert reused["date"] == receipt["date"]
    assert reused["reuse"]["network_attempts"] == 0
    source.write_bytes(b"changed data")
    with pytest.raises(ValueError, match="input hash mismatch"):
        optic_lobe_assets.reuse_inputs(new, reference, files)
    assert (new / next(iter(files))).read_bytes() == body
