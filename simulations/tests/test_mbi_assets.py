"""Recorded primary identity and backend adaptation have explicit boundaries."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes import mbi_download
from probes.mbi_assets import copy_verified, headless


def test_headless_preserves_computation_and_only_changes_backend():
    source = "import matplotlib as mpl\nmpl.use('tkagg')\nx = 3 * 7\n"
    edited, count = headless(source)
    assert count == 1 and edited.endswith("x = 3 * 7\n")
    assert "mpl.use('Agg')" in edited
    assert headless(edited) == (edited, 0)
    with pytest.raises(ValueError, match="Unexpected change"):
        headless('import matplotlib as mpl\nmpl.use("tkagg")\n')


def test_primary_hash_and_changed_run_copy_are_not_silently_overwritten(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    source = tmp_path / "assets/recording.csv"
    source.parent.mkdir()
    payload = b"time,voltage\n0,1\n"
    source.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "run/source/data/recording.csv"
    copy_verified(source, target, len(payload), sha)
    assert target.read_bytes() == payload
    target.write_bytes(b"local modification")
    with pytest.raises(ValueError, match="Preserving changed"):
        copy_verified(source, target, len(payload), sha)
    assert target.read_bytes() == b"local modification"
    source.write_bytes(b"wrong version")
    with pytest.raises(ValueError, match="primary identity"):
        copy_verified(source, target, len(payload), sha)


def test_catalog_identity_rejects_new_version_or_content():
    files = [
        {"id": "a", "path": "trace.csv", "bytes": 3, "version": 1, "sha256": "a" * 64}
    ]
    identity = mbi_download.catalog_identity(files)
    files[0]["version"] = 2
    assert mbi_download.catalog_identity(files) != identity
    files[0]["version"] = 1
    files[0]["sha256"] = "b" * 64
    assert mbi_download.catalog_identity(files) != identity


def test_persistent_two_failed_attempts_do_not_restart_download(tmp_path, monkeypatch):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(mbi_download, "WORK", tmp_path)
    monkeypatch.setattr(mbi_download, "ROOT", tmp_path)
    base = tmp_path / "SIM-025/assets"
    base.mkdir(parents=True)
    item = {
        "id": "a",
        "path": "recording.csv",
        "bytes": 3,
        "version": 1,
        "sha256": "a" * 64,
        "download": "https://osf.io/download/a/",
    }
    monkeypatch.setattr(mbi_download, "read_catalog", lambda _: {"files": [item]})
    (base / "download-requests.json").write_text(
        json.dumps(
            {
                "a": [
                    {"attempt": 1, "status": "failed"},
                    {"attempt": 2, "status": "failed"},
                ]
            }
        )
    )

    def unexpected_request(*args, **kwargs):
        pytest.fail("A third download is forbidden")

    monkeypatch.setattr(mbi_download.urllib.request, "urlopen", unexpected_request)
    with pytest.raises(ValueError, match="two attempts"):
        mbi_download.acquire()
    result = json.loads((base / "inputs.json").read_text())
    assert result["complete"] and result["errors"] == ["recording.csv"]
