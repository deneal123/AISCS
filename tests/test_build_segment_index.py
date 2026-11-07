import hashlib
import json
import random
import sqlite3

import numpy as np
import pytest

from scripts.audit_segment_index import audit as audit_segments
from scripts.audit_segment_index import exact_boxes, independently_check
from scripts.build_morphology_bounds import build_index
from scripts.build_segment_index import build
from scripts.resume_segment_index_parallel import resume
from service.infrastructure.connectome.morphology_repository import BASE
from service.infrastructure.stimulation.segment_bounds import segment_boxes
from service.infrastructure.stimulation.spatial_candidates import spatial_candidates


def test_build_resume_and_conservative_rtree_rounding(tmp_path):
    directory = tmp_path / "sources"
    (directory / "raw").mkdir(parents=True)
    (directory / "receipts").mkdir()
    texts = []
    for body in (1, 2):
        text = f"1 1 {body * 12345} -34567 1234 1 -1\n2 1 9999 -5 7000 1 1\n"
        texts.append(text)
        raw = text.encode()
        (directory / "raw" / f"{body}.swc").write_bytes(raw)
        receipt = {"body_id": body, "url": BASE + f"{body}.swc",
                   "sha256": hashlib.sha256(raw).hexdigest()}
        (directory / "receipts" / f"{body}.json").write_text(json.dumps(receipt))
    source, output, audit = (tmp_path / name for name in ("source.db", "segments.db", "audit.json"))
    build_index([1, 2], [directory], source, "graph")
    audit.write_text(json.dumps({"format": "malecns-bounds-audit-v1", "verified": 2,
                                 "index_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                                 "graph_sha256": "graph"}))
    assert build(source, audit, output, [directory], limit=1)["indexed"] == 1
    assert resume(source, audit, output, [directory], workers=2)["indexed"] == 2
    assert build(source, audit, output, [directory])["indexed"] == 2
    assert build(source, audit, output, [directory])["indexed"] == 2
    with sqlite3.connect(output) as db:
        for ordinal, text in enumerate(texts):
            expected = segment_boxes(text)
            stored = db.execute("SELECT min_x, min_y, min_z, max_x, max_y, max_z FROM boxes "
                                "WHERE id >= ? AND id < ? ORDER BY id",
                                (ordinal * 2**32, (ordinal + 1) * 2**32)).fetchall()
            actual = np.array(stored)
            assert np.all(actual[:, :3] <= expected[:, :3])
            assert np.all(actual[:, 3:] >= expected[:, 3:])
    report = audit_segments(source, audit, output, [directory])
    assert report["verified"] == 2
    assert audit_segments(source, audit, output, [directory], workers=2) == report
    segment_audit = tmp_path / "segments.audit.json"
    segment_audit.write_text(json.dumps(report))
    args = (source, [1, 2], "graph", [directory], [[80, 0, 56], [200, 200, 200]], 2)
    ordinary = spatial_candidates(*args, audit_report=audit)
    accelerated = spatial_candidates(*args, audit_report=audit,
                                     segment_index=output, segment_audit=segment_audit)
    assert accelerated["candidates"] == ordinary["candidates"]
    assert accelerated["candidates"]
    randomizer = random.Random(241)
    for _ in range(50):
        contacts = [[randomizer.uniform(-300, 300) for _ in range(3)] for _ in range(2)]
        query = (source, [1, 2], "graph", [directory], contacts, randomizer.uniform(0, 200))
        expected = spatial_candidates(*query, audit_report=audit)
        observed = spatial_candidates(*query, audit_report=audit, segment_index=output,
                                      segment_audit=segment_audit)
        assert observed["candidates"] == expected["candidates"]
    with pytest.raises(ValueError, match="Both segment index"):
        spatial_candidates(*args, audit_report=audit, segment_index=output)
    with sqlite3.connect(output) as db:
        first_id = db.execute("SELECT min(id) FROM boxes").fetchone()[0]
        db.execute("UPDATE boxes SET min_x = -1, max_x = 0 WHERE id = ?", (first_id,))
    with pytest.raises(ValueError, match="Segment missing"):
        audit_segments(source, audit, output, [directory])
    with pytest.raises(ValueError, match="Segment missing"):
        audit_segments(source, audit, output, [directory], workers=2)
    with pytest.raises(ValueError, match="changed since audit"):
        spatial_candidates(*args, audit_report=audit, segment_index=output,
                           segment_audit=segment_audit)
    audit.write_text('{}')
    with pytest.raises(ValueError, match="audited"):
        build(source, audit, output, [directory])


def test_audit_rejects_endpoints_in_separate_boxes():
    swc = "1 1 0 0 0 1 -1\n2 1 1250 0 0 1 1\n"
    with pytest.raises(ValueError, match="Segment missing"):
        independently_check(swc, [[0, 0, 0, 1, 1, 1], [9, 0, 0, 10, 1, 1]])


def test_exact_box_lookup_matches_range_across_batches_and_detects_missing_row():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE VIRTUAL TABLE boxes USING rtree(id,min_x,max_x,min_y,max_y,min_z,max_z)')
        base = 7 * 2**32
        db.executemany('INSERT INTO boxes VALUES (?,?,?,?,?,?,?)',
                       [(base + i, i, i + 1, 0, 1, 0, 1) for i in range(1200)])
        db.execute('INSERT INTO boxes VALUES (?,?,?,?,?,?,?)', (base + 2**32, 0, 1, 0, 1, 0, 1))
        previous = db.execute('SELECT min_x,min_y,min_z,max_x,max_y,max_z FROM boxes '
                              'WHERE id >= ? AND id < ? ORDER BY id',
                              (base, base + 2**32)).fetchall()
        assert exact_boxes(db, 7, 1200) == previous
        plan = db.execute('EXPLAIN QUERY PLAN SELECT * FROM boxes WHERE id IN (?,?,?)',
                          (base, base + 1, base + 2)).fetchall()
        assert any('VIRTUAL TABLE INDEX 1:' in row[3] for row in plan)
        db.execute('DELETE FROM boxes WHERE id=?', (base + 700,))
        with pytest.raises(ValueError, match='Missing or unexpected boxes'):
            exact_boxes(db, 7, 1200)
