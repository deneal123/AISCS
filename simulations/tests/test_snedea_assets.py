"""The browser run accepts only pinned input contents, never a missing-data fallback."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.snedea_assets import identity


def test_changed_input_fails_even_when_filename_is_the_same(tmp_path):
    path = tmp_path / "connectome.bin.gz"
    value = b"registered binary fixture"
    path.write_bytes(value)
    blob = hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()
    assert identity(path, blob)["sha256"] == hashlib.sha256(value).hexdigest()
    path.write_bytes(b"fallback binary fixture")
    with pytest.raises(ValueError, match="Git blob differs"):
        identity(path, blob)
