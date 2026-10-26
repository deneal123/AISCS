"""A sealed bundle needs exact bytes and safe regular Git paths."""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.fcta_assets import identity, pinned_tree


def test_git_identity_distinguishes_checkout_newlines(tmp_path):
    path = tmp_path / "README.md"
    value = b"upstream\n"
    path.write_bytes(value)
    blob = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    assert identity(path, blob)["sha256"] == hashlib.sha256(value).hexdigest()
    path.write_bytes(b"upstream\r\n")
    with pytest.raises(ValueError, match="Git blob differs"):
        identity(path, blob)


@pytest.mark.parametrize(
    "entry",
    [
        "100644 blob " + "a" * 40 + "\t../outside",
        "120000 blob " + "a" * 40 + "\tlink",
        "100644 blob " + "a" * 40 + "\t/absolute",
    ],
)
def test_tree_rejects_unconfined_or_nonregular_inputs(tmp_path, monkeypatch, entry):
    monkeypatch.setattr(
        subprocess, "check_output", lambda *args, **kwargs: entry + "\n"
    )
    with pytest.raises(ValueError, match="regular relative files"):
        pinned_tree(tmp_path)
