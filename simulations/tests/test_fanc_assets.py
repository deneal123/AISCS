"""Sparse SWC acquisition must bind bytes to the exact registered Git object."""

import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes import fanc_assets


@pytest.mark.parametrize("corrupt", [False, True])
def test_only_pinned_swc_bytes_are_accepted(tmp_path, monkeypatch, corrupt):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(fanc_assets, "ROOT", tmp_path)
    monkeypatch.setattr(
        fanc_assets,
        "load",
        lambda _: {
            "candidates": [{"id": "SIM-012", "commit": "pinned", "path": "repo"}]
        },
    )
    body = b"1 0 1 2 3 1 -1\n"
    oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()

    def tree(args, **kwargs):
        return f"100644 blob {oid}\t{args[-1]}\n"

    calls = []

    def download(url, **kwargs):
        calls.append(url)
        return io.BytesIO(b"<html>error</html>" if corrupt else body)

    monkeypatch.setattr(fanc_assets.subprocess, "check_output", tree)
    monkeypatch.setattr(fanc_assets.urllib.request, "urlopen", download)
    monkeypatch.setattr(fanc_assets, "save", lambda p, obj: p.write_text(str(obj)))
    run = tmp_path / "run"
    run.mkdir()
    if corrupt:
        with pytest.raises(ValueError, match="unavailable twice"):
            fanc_assets.hydrate(run)
        assert len(calls) == 2 and not (run / "fanc-inputs.json").exists()
    else:
        fanc_assets.hydrate(run)
        assert len(calls) == 2 and (run / "fanc-inputs.json").is_file()
        assert all(p.read_bytes() == body for p in (run / "inputs").glob("*.swc"))
