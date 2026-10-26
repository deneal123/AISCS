"""Reject corrupt public inputs instead of accepting a successful HTTP response."""

import base64
import hashlib
import io
import subprocess
import sys
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from probes.banc_assets import download, restore_blob


class Response(io.BytesIO):
    def __init__(self, body, *, digest=None, length=None):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(body) if length is None else length)
        self.headers["x-goog-hash"] = "crc32c=test"
        self.headers["x-goog-hash"] = "md5=" + (
            digest or base64.b64encode(hashlib.md5(body).digest()).decode()
        )


@pytest.mark.parametrize("kind", ["html", "truncated", "wrong_md5"])
def test_invalid_arrow_is_rejected_twice(monkeypatch, tmp_path, kind):
    body = b"<html>error page</html>" if kind == "html" else b"ARROW1payloadARROW1"
    calls = []

    def opened(*args, **kwargs):
        calls.append(args)
        return Response(
            body,
            digest="invalid" if kind == "wrong_md5" else None,
            length=len(body) + 1 if kind == "truncated" else None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", opened)
    target = tmp_path / "edge.feather"
    with pytest.raises(ValueError, match="failed twice"):
        download("https://example.invalid/edge", target)
    assert len(calls) == 2
    assert not target.exists() and not target.with_suffix(".feather.part").exists()


def test_valid_arrow_envelope_records_primary_checksum(monkeypatch, tmp_path):
    body = b"ARROW1test-payloadARROW1"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response(body))
    target = tmp_path / "edge.feather"
    receipt = download("https://example.invalid/edge", target)
    assert receipt["attempt"] == 1 and receipt["bytes"] == len(body)
    assert target.read_bytes() == body
    assert receipt["sha256"] == hashlib.sha256(body).hexdigest()


def test_hydration_preserves_attested_windows_checkout_bytes(monkeypatch, tmp_path):
    blob = b"line one\nline two\n"
    oid = hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()
    checkout = blob.replace(b"\n", b"\r\n")
    target = tmp_path / "README.md"
    target.write_bytes(checkout)

    def git(args, **kwargs):
        if args[1] == "ls-tree":
            return f"100644 blob {oid} {len(blob)}\tREADME.md\n"
        return blob

    monkeypatch.setattr(subprocess, "check_output", git)
    receipt = restore_blob(tmp_path, "commit", "README.md", target)
    assert target.read_bytes() == checkout
    assert receipt["checkout_eol_conversion"] is True
    assert receipt["sha256"] == hashlib.sha256(checkout).hexdigest()
