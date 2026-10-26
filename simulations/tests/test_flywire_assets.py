"""Primary v630 data must match exact Git identity, not just parse as gzip."""

import gzip
import hashlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.flywire_assets import fetch, identity


def oid(body):
    return hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()


def test_corrupt_route_exhausts_persisted_attempt_budget(monkeypatch, tmp_path):
    attempts = [{"attempt": 1, "status": "prefix_only_preflight"}]
    calls = []
    persisted = []

    def opened(*args, **kwargs):
        calls.append(args)
        return io.BytesIO(b"<html>not a connectome</html>")

    monkeypatch.setattr("urllib.request.urlopen", opened)
    target = tmp_path / "connections.csv.gz"
    with pytest.raises(ValueError, match="exhausted"):
        fetch(
            "https://example.invalid/input",
            target,
            "0" * 40,
            attempts,
            lambda: persisted.append(len(attempts)),
        )
    assert len(calls) == 1 and len(attempts) == 2 and persisted == [2, 2]
    assert not target.exists() and not target.with_suffix(".gz.partial").exists()
    with pytest.raises(ValueError, match="exhausted"):
        fetch("https://example.invalid/input", target, "0" * 40, attempts, lambda: None)
    assert len(calls) == 1


def test_valid_gzip_checks_git_and_crc(tmp_path):
    body = gzip.compress(b"pre_root_id,post_root_id\n1,2\n", mtime=0)
    target = tmp_path / "connections.csv.gz"
    target.write_bytes(body)
    assert identity(target, oid(body))["gzip_crc_verified"] is True
    truncated = body[:-3]
    target.write_bytes(truncated)
    with pytest.raises(EOFError):
        identity(target, oid(truncated))
