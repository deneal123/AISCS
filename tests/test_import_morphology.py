import base64
import hashlib

import httpx

from scripts.import_morphology import import_one
from scripts.prepare_full_morphology import verified_receipt


def test_import_requires_source_checksum_and_preserves_input(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    (output / "raw").mkdir(parents=True)
    (output / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n"
    (source / "42.swc").write_bytes(raw)
    digest = base64.b64encode(hashlib.md5(raw, usedforsecurity=False).digest()).decode()

    def respond(request):
        assert request.method == "HEAD"
        return httpx.Response(
            200,
            headers={"x-goog-hash": "crc32c=123, md5=" + digest, "content-length": str(len(raw))},
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert import_one(client, source, output, 42)["state"] == "verified"
        assert import_one(client, source, output, 43)["state"] == "missing"
    assert verified_receipt(output, 42)
    assert (source / "42.swc").read_bytes() == raw


def test_checksum_mismatch_never_creates_receipt(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    source.mkdir()
    (output / "raw").mkdir(parents=True)
    (output / "receipts").mkdir()
    (source / "42.swc").write_text("1 0 0 0 0 1 -1\n")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"x-goog-hash": "md5=wrong", "content-length": "1"}
        )
    )
    with httpx.Client(transport=transport) as client:
        assert import_one(client, source, output, 42)["state"] == "failed"
    assert not (output / "receipts" / "42.json").exists()
