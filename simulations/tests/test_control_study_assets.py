"""Do not turn a successful archive download into unverified study inputs."""

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes.control_study_assets import COMMIT, compatibility, restore


def test_archive_tables_require_exact_blob_and_preserve_working_source(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    body = b"model,loss\nconnectome,1.2\n"
    expected = hashlib.sha1(
        b"blob " + str(len(body)).encode() + b"\0" + body
    ).hexdigest()
    archive = tmp_path / "study.zip"
    name = "results/summary.csv"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("study-" + COMMIT + "/" + name, body)
    with pytest.raises(ValueError, match="blob mismatch"):
        restore(archive, run, {name: "0" * 40})
    assert not (run / "source" / name).exists()
    records = restore(archive, run, {name: expected})
    assert records[0]["sha256"] == hashlib.sha256(body).hexdigest()
    assert (run / "source" / name).read_bytes() == body
    (run / "source" / name).write_bytes(b"working source preserved")
    assert restore(archive, run, {name: expected}) == []
    assert (run / "source" / name).read_bytes() == b"working source preserved"


def test_archive_path_traversal_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path / "owned")
    run = tmp_path / "owned/run"
    run.mkdir(parents=True)
    archive = tmp_path / "study.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("study-" + COMMIT + "/../../../../outside.csv", b"x")
    with pytest.raises(ValueError, match="Run directory"):
        restore(archive, run, {"../../../../outside.csv": "0" * 40})
    assert not (tmp_path / "outside.csv").exists()


def test_packaging_repair_retains_overrides_and_rejects_unreviewed_source():
    original = b"return get_default_config(overrides=DEFAULT_CONFIG_OVERRIDES)\r\n"
    fixed, reasons = compatibility(original, alias=True)
    assert b"overrides=DEFAULT_CONFIG_OVERRIDES" in fixed
    assert b"config/solver.yaml" in fixed and b"FLYVIS_REPO_ROOT =" in fixed
    assert len(reasons) == 2 and b"\r\n" in fixed
    with pytest.raises(ValueError, match="configuration call"):
        compatibility(fixed)
