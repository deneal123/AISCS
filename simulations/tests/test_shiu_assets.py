"""Original graph inputs require exact Git identity and preserve changed work."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes.shiu_assets import copy_verified, identity


def test_original_identity_rejects_changed_input_and_preserves_work(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    source = tmp_path / "primary.csv"
    body = b"id\n720575940624963786\n"
    source.write_bytes(body)
    oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    target = tmp_path / "run/source/completeness.csv"
    result = copy_verified(source, target, oid)
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert target.read_bytes() == body
    target.write_bytes(b"intentional local change")
    with pytest.raises(ValueError, match="Git blob mismatch"):
        copy_verified(source, target, oid)
    assert target.read_bytes() == b"intentional local change"
    source.write_bytes(b"different primary release")
    with pytest.raises(ValueError, match="Git blob mismatch"):
        identity(source, oid)


def test_copy_rejects_output_outside_simulation_work(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path / "work")
    source = tmp_path / "work/primary"
    source.parent.mkdir()
    source.write_bytes(b"primary")
    with pytest.raises(ValueError, match="strictly inside"):
        copy_verified(source, tmp_path / "foreign", "0" * 40)
