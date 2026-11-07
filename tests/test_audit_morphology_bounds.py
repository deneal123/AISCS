import hashlib
import json
import sqlite3

import pytest

from scripts.audit_morphology_bounds import BASE, audit
from scripts.build_morphology_bounds import build_index


def test_independent_audit_detects_changed_bounds_and_source(tmp_path):
    directory = tmp_path / "morphology"
    (directory / "raw").mkdir(parents=True)
    (directory / "receipts").mkdir()
    swc = b"1 1 0 0 0 1 -1\n2 1 1250 0 0 1 1\n"
    (directory / "raw" / "1.swc").write_bytes(swc)
    receipt = {"body_id": 1, "sha256": hashlib.sha256(swc).hexdigest(), "url": BASE + "1.swc"}
    (directory / "receipts" / "1.json").write_text(json.dumps(receipt), encoding="utf-8")
    index = tmp_path / "bounds.sqlite"
    build_index([1], [directory], index, "graph")
    assert audit(index, [1], "graph", [directory])["verified"] == 1
    assert audit(index, [1], "graph", [directory], workers=2)["verified"] == 1
    with sqlite3.connect(index) as db:
        db.execute("UPDATE bounds SET max_x=9 WHERE body_id=1")
    with pytest.raises(ValueError, match="Bounding box mismatch"):
        audit(index, [1], "graph", [directory])
    with sqlite3.connect(index) as db:
        db.execute("UPDATE bounds SET max_x=10 WHERE body_id=1")
    (directory / "raw" / "1.swc").write_bytes(swc + b"# changed\n")
    with pytest.raises(ValueError, match="Source or receipt mismatch"):
        audit(index, [1], "graph", [directory])
