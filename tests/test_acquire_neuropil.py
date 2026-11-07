import hashlib
import json

import pytest

from scripts.acquire_neuropil import acquire_one


def test_acquisition_checks_source_size_hash_and_preserves_existing(tmp_path):
    raw = b"source mesh"
    digest = hashlib.md5(raw).hexdigest()

    def request(url, *, head=False, maximum=0):
        if url.endswith("/5:0"):
            return json.dumps({"fragments": ["LegNp(T1)(L).ngmesh"]}).encode()
        if head:
            return {"Content-Length": str(len(raw)), "ETag": f'"{digest}"'}
        assert maximum == len(raw)
        return raw

    record = acquire_one(tmp_path, "malecns-vnc-neuropil-roi-v0", "5", "LegNp(T1)(L)", request)
    assert record["md5_verified"] and record["sha256"] == hashlib.sha256(raw).hexdigest()
    repeated = acquire_one(tmp_path, "malecns-vnc-neuropil-roi-v0", "5", "LegNp(T1)(L)", request)
    assert repeated == record
    (tmp_path / record["file"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="MD5"):
        acquire_one(tmp_path, "malecns-vnc-neuropil-roi-v0", "5", "LegNp(T1)(L)", request)


def test_acquisition_rejects_untrusted_paths(tmp_path):
    def request(url, **kwargs):
        return b'{"fragments":["../bad.ngmesh"]}'

    with pytest.raises(ValueError, match="fragment"):
        acquire_one(tmp_path, "fullbrain-roi-v4", "1", "region", request)
    with pytest.raises(ValueError, match="identity"):
        acquire_one(tmp_path, "../bad", "1", "region", request)
