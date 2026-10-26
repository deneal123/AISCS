"""The port's FlyWire inputs require pinned Git identities."""

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes.snntorch_assets import COMMIT, restore


def test_inputs_require_blob_identity_and_preserve_changed_work(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    member = "data/example.csv"
    body = b"id\n720575940624963786\n"
    oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    archive = tmp_path / "input.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("fly-brain-snntorch-" + COMMIT + "/" + member, body)
    with pytest.raises(ValueError, match="blob mismatch"):
        restore(archive, run, {member: "0" * 40})
    assert not (run / "source" / member).exists()
    result = restore(archive, run, {member: oid})
    assert result[0]["sha256"] == hashlib.sha256(body).hexdigest()
    assert (run / "source" / member).read_bytes() == body
    (run / "source" / member).write_bytes(b"working modification")
    with pytest.raises(ValueError, match="differs"):
        restore(archive, run, {member: oid})
    assert (run / "source" / member).read_bytes() == b"working modification"
