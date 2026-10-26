"""Do not turn HTTP success into acceptance of a different ESN matrix."""

import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import simctl
from probes import conn_esn_assets


@pytest.mark.parametrize("corrupt", [False, True])
def test_esn_matrix_binding_to_git_blob(tmp_path, monkeypatch, corrupt):
    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(conn_esn_assets, "ROOT", tmp_path)
    monkeypatch.setattr(
        conn_esn_assets,
        "load",
        lambda _: {
            "candidates": [
                {
                    "id": "SIM-013",
                    "commit": "pinned",
                    "path": "repo",
                    "repository": "author/repo",
                }
            ]
        },
    )
    body = b"x1,x2\n0,1\n1,0\n"
    oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    monkeypatch.setattr(
        conn_esn_assets.subprocess,
        "check_output",
        lambda args, **kw: f"100644 blob {oid}\t{args[-1]}\n",
    )
    calls = []

    def opened(url, **kwargs):
        calls.append(url)
        return io.BytesIO(b"x1,x2\n9,9\n9,9\n" if corrupt else body)

    monkeypatch.setattr(conn_esn_assets.urllib.request, "urlopen", opened)
    monkeypatch.setattr(conn_esn_assets, "prepare_font", lambda _: None)
    monkeypatch.setattr(conn_esn_assets, "save", lambda p, v: p.write_text(str(v)))
    run = tmp_path / "run"
    run.mkdir()
    if corrupt:
        with pytest.raises(ValueError, match="unavailable twice"):
            conn_esn_assets.hydrate(run)
        assert len(calls) == 2 and not (run / "conn-esn-inputs.json").exists()
    else:
        conn_esn_assets.hydrate(run)
        assert len(calls) == 6
        assert len(list((run / "inputs").glob("*/*.csv"))) == 6
        assert (run / "conn-esn-inputs.json").is_file()


@pytest.mark.parametrize("corrupt", [False, True])
def test_frozen_esn_replay_checks_both_hashes_without_network(
    tmp_path, monkeypatch, corrupt
):
    import json

    monkeypatch.setattr(simctl, "WORK", tmp_path)
    monkeypatch.setattr(conn_esn_assets, "ROOT", tmp_path)
    monkeypatch.setattr(conn_esn_assets, "load", lambda p: json.loads(p.read_text()))
    monkeypatch.setattr(
        conn_esn_assets, "save", lambda p, v: p.write_text(json.dumps(v))
    )
    monkeypatch.setattr(conn_esn_assets, "prepare_font", lambda _: None)
    original = tmp_path / "SIM-013/old"
    inputs = []
    body = b"x1,x2\n0,1\n1,0\n"
    for stage in ("larva", "adult"):
        for group in ("connectome", "random", "cfg"):
            name = f"inputs/{stage}/{group}.csv"
            path = original / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            inputs.append(
                {
                    "file": name,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "git_blob": hashlib.sha1(
                        b"blob " + str(len(body)).encode() + b"\0" + body
                    ).hexdigest(),
                }
            )
    manifest = original / "conn-esn-inputs.json"
    manifest.write_text(json.dumps({"commit": "pin", "inputs": inputs}))
    row = {
        "commit": "pin",
        "frozen_inputs": {
            "path": manifest.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
    }
    if corrupt:
        (original / inputs[0]["file"]).write_bytes(b"different")
    run = tmp_path / "SIM-013/new"
    run.mkdir(parents=True)
    if corrupt:
        with pytest.raises(ValueError, match="matrix changed"):
            conn_esn_assets.restore_frozen(run, row)
    else:
        conn_esn_assets.restore_frozen(run, row)
        assert len(list((run / "inputs").glob("*/*.csv"))) == 6
        assert (
            json.loads((run / "conn-esn-inputs.json").read_text())["reuse"][
                "network_attempts"
            ]
            == 0
        )
