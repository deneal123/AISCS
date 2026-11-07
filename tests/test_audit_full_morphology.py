import hashlib
import json

from scripts.audit_full_morphology import audit
from scripts.prepare_full_morphology import BASE


def test_audit_checks_each_identity_and_accepts_valid_fallback(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        (directory / "raw").mkdir(parents=True)
        (directory / "receipts").mkdir()
    raw = b"1 0 0 0 0 1 -1\n"
    receipt = {"body_id": 1, "url": BASE + "1.swc", "sha256": hashlib.sha256(raw).hexdigest()}
    (second / "raw" / "1.swc").write_bytes(raw)
    (second / "receipts" / "1.json").write_text(json.dumps(receipt))
    assert audit([1, 2], [first, second])["unavailable_ids"] == [2]
    (second / "raw" / "1.swc").write_bytes(raw + b"bad")
    assert audit([1], [first, second])["complete"] is False
