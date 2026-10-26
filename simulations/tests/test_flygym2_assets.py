"""A source archive must match the registered FlyGym Git blobs."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory
import simctl
from probes import flygym2_assets


@pytest.mark.parametrize("corrupt", [False, True])
@pytest.mark.parametrize("candidate", ["SIM-020", "SIM-021"])
def test_bundled_assets_require_git_identity(tmp_path, monkeypatch, corrupt, candidate):
    work = tmp_path / "work"
    run = work / candidate / "run"
    run.mkdir(parents=True)
    commit = (
        flygym2_assets.COMMIT
        if candidate == "SIM-020"
        else flygym2_assets.LEGACY_COMMIT
    )
    member = (
        "src/flygym/mesh.stl"
        if candidate == "SIM-020"
        else "flygym_gymnasium/data/mesh.stl"
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "id": candidate,
                        "commit": commit,
                        "repository": "NeLy-EPFL/flygym",
                        "path": "source-repository",
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "WORK", work)
    monkeypatch.setattr(inventory, "REGISTRY", registry)
    monkeypatch.setattr(simctl, "WORK", work)
    payload = b"pinned mesh bytes"
    oid = hashlib.sha1(
        b"blob " + str(len(payload)).encode() + b"\0" + payload
    ).hexdigest()
    assets = work / candidate / "assets"
    assets.mkdir()
    with zipfile.ZipFile(assets / (commit + ".zip"), "w") as bundle:
        prefix = "flygym-" + commit + "/"
        bundle.writestr(prefix + member, b"bad" if corrupt else payload)
        bundle.writestr(prefix + "tests/retained.py", b"original test")
    tree = f"100644 blob {oid}\t{member}\n"
    tree += "100644 blob " + "0" * 40 + "\ttests/retained.py\n"
    monkeypatch.setattr(flygym2_assets.subprocess, "check_output", lambda *a, **k: tree)
    retained = run / "source/tests/retained.py"
    retained.parent.mkdir(parents=True)
    retained.write_bytes(b"existing working file")
    if corrupt:
        with pytest.raises(ValueError, match="blob mismatch"):
            flygym2_assets.hydrate(run, candidate_id=candidate)
        assert not (run / "source" / member).exists()
    else:
        flygym2_assets.hydrate(run, candidate_id=candidate)
        assert (run / "source" / member).read_bytes() == payload
        receipt = json.loads((run / "bundled-assets.json").read_text())
        assert len(receipt["restored"]) == 1
        assert receipt["restored"][0]["git_blob"] == oid
    assert retained.read_bytes() == b"existing working file"
