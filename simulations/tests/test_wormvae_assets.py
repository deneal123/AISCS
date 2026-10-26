"""A changed graph or recording must never pass pinned-input verification."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.wormvae_assets import identity


def test_worm_input_requires_exact_primary_bytes(tmp_path):
    path = tmp_path / "data.mat"
    raw = b"MATLAB primary bytes"
    path.write_bytes(raw)
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert identity(path, oid)["sha256"] == hashlib.sha256(raw).hexdigest()
    path.write_bytes(raw + b"changed")
    with pytest.raises(ValueError, match="pinned Git blob"):
        identity(path, oid)
