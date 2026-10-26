"""Exact inputs and rejection of accidental substitution in the VNC profile."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.pugliese_assets import FILES, identity


def test_identity_accepts_only_expected_git_blob(tmp_path):
    path = tmp_path / "input.csv"
    value = b"bodyId_pre,0\n10000,0.0\n"
    path.write_bytes(value)
    oid = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    result = identity(path, oid, len(value))
    assert result["sha256"] == hashlib.sha256(value).hexdigest()
    with pytest.raises(ValueError, match="Git identity differs"):
        identity(path, "0" * 40, len(value))
    with pytest.raises(ValueError, match="size differs"):
        identity(path, oid, len(value) + 1)


def test_only_default_tutorial_inputs_are_registered():
    assert len(FILES) == 2
    assert all(name.startswith("data/manc t1 connectome data/") for name in FILES)
    assert sum(item[1] for item in FILES.values()) == 85709265
