import json

import httpx
import numpy as np
import pytest

from scripts import prepare_full_morphology as acquire


def test_only_registered_sorted_ids_with_matching_manifest_are_accepted(tmp_path, monkeypatch):
    ids, manifest = tmp_path / "ids.npy", tmp_path / "manifest.json"
    np.save(ids, np.arange(1, 166701, dtype=np.int64))
    manifest.write_text(json.dumps({"arrays": {"ids.npy": acquire.sha256(ids)}}))
    monkeypatch.setattr(acquire, "MANIFEST_SHA256", acquire.sha256(manifest))
    result = acquire.registered_ids(ids, manifest)
    assert len(result) == 166700 and result[0] == 1 and result[-1] == 166700
    with ids.open("ab") as stream:
        stream.write(b"damaged")
    with pytest.raises(ValueError, match="IDs"):
        acquire.registered_ids(ids, manifest)


def test_download_receipt_checks_identity_url_hash_and_source_geometry(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(200, text="1 0 0 0 0 1 -1\n2 0 10 0 0 1 1\n")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = acquire.download(client, tmp_path, 123)
    assert result["state"] == "downloaded" and len(calls) == 1
    assert acquire.verified_receipt(tmp_path, 123)
    (tmp_path / "raw" / "123.swc").write_text("tampered")
    assert not acquire.verified_receipt(tmp_path, 123)


def test_bad_skeleton_retries_twice_without_publishing_receipt(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    calls = []

    def respond(request):
        calls.append(request.url)
        return httpx.Response(200, text="not an SWC")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = acquire.download(client, tmp_path, 123)
    assert result["state"] == "unavailable" and len(calls) == 2
    assert not acquire.verified_receipt(tmp_path, 123)


@pytest.mark.parametrize("invalid", ["null", "[]", "1", '"text"', "{"])
def test_invalid_receipt_is_reacquired_instead_of_crashing(tmp_path, invalid):
    (tmp_path / "raw").mkdir()
    (tmp_path / "receipts").mkdir()
    (tmp_path / "raw" / "123.swc").write_text("1 0 0 0 0 1 -1\n")
    (tmp_path / "receipts" / "123.json").write_text(invalid)
    assert not acquire.verified_receipt(tmp_path, 123)
