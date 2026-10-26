"""Pretrained files must originate in the exact author-hashed archive."""

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import simctl
from probes import scalebreak_assets as assets


def test_corrupt_pretrained_archive_does_not_create_replacement_weights(
    tmp_path, monkeypatch
):
    work = tmp_path / "work"
    run = work / "SIM-019/20261026T000000Z-case"
    run.mkdir(parents=True)
    source = work / "SIM-019/assets/results_pretrained_models.zip"
    source.parent.mkdir()
    source.write_bytes(b"<html>not model weights</html>")
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "WORK", work)
    monkeypatch.setattr(simctl, "WORK", work)
    with pytest.raises(ValueError, match="checksum mismatch"):
        assets.hydrate(run)
    assert not (run / "assets").exists()


def test_only_registered_model_members_are_restored(tmp_path, monkeypatch):
    work = tmp_path / "work"
    run = work / "SIM-019/20261026T000000Z-case"
    run.mkdir(parents=True)
    source = work / "SIM-019/assets/results_pretrained_models.zip"
    source.parent.mkdir()
    with zipfile.ZipFile(source, "w") as bundle:
        for name in assets.FILES:
            bundle.writestr(assets.PREFIX + name, b"fixture " + name.encode())
        bundle.writestr("results/flow/0000/001/best_chkpt", b"unselected model")
        bundle.writestr("../../escape", b"not selected")
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "WORK", work)
    monkeypatch.setattr(simctl, "WORK", work)
    monkeypatch.setattr(
        assets, "SHA256", hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assets.hydrate(run)
    restored = [p for p in (run / "assets").rglob("*") if p.is_file()]
    assert len(restored) == len(assets.FILES)
    assert not (run / "assets/pretrained/results/flow/0000/001").exists()
    assert not (tmp_path / "escape").exists()
