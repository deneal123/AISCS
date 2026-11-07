"""Independently verify that every source segment is enclosed by the R-tree."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_segment_index import digest  # noqa: E402
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402


def independently_check(swc: str, stored):
    """Check both endpoints of every actual edge against the same stored box."""
    nodes = {}
    for line in swc.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) != 7:
            raise ValueError("Malformed source")
        node, parent = int(fields[0]), int(fields[6])
        point = tuple(float(x) * 0.008 for x in fields[2:5])
        if node <= 0 or node in nodes or not all(np.isfinite(point)) or node == parent:
            raise ValueError("Invalid source vertex")
        nodes[node] = (point, parent)
    parents = {parent for _, parent in nodes.values() if parent != -1}
    edges = []
    for node, (point, parent) in nodes.items():
        if parent == -1:
            if node not in parents:
                edges.append((point, point))
        elif parent not in nodes:
            raise ValueError("Missing source parent")
        else:
            edges.append((nodes[parent][0], point))
    boxes = np.asarray(stored, dtype=float)
    if (
        not edges
        or boxes.ndim != 2
        or boxes.shape[1] != 6
        or not len(boxes)
        or not np.isfinite(boxes).all()
        or np.any(boxes[:, :3] > boxes[:, 3:])
    ):
        raise ValueError("Invalid stored geometry")
    for offset in range(0, len(edges), 32):
        points = np.asarray(edges[offset : offset + 32])
        lo = points.min(axis=1)[:, None, :]
        hi = points.max(axis=1)[:, None, :]
        covered = np.all(boxes[None, :, :3] <= lo, axis=2) & np.all(
            boxes[None, :, 3:] >= hi, axis=2
        )
        if not np.all(np.any(covered, axis=1)):
            raise ValueError("Segment missing from R-tree")


def _check_source(item):
    body, sha, directories, boxes = item
    swc = read_skeleton(body, directories, expected_sha256=sha)["swc"]
    independently_check(swc, boxes)
    return body


def exact_boxes(db, ordinal: int, count: int):
    """Fetch expected R-tree rows by exact ID without a full-table range scan."""
    result = []
    base = ordinal * 2**32
    for start in range(0, count, 512):
        expected = list(range(base + start, base + min(start + 512, count)))
        placeholders = ",".join("?" for _ in expected)
        rows = db.execute(
            "SELECT id, min_x, min_y, min_z, max_x, max_y, max_z "
            f"FROM boxes WHERE id IN ({placeholders})", expected
        ).fetchall()
        rows.sort(key=lambda row: row[0])
        if [row[0] for row in rows] != expected:
            raise ValueError("Missing or unexpected boxes")
        result.extend(row[1:] for row in rows)
    return result


def audit(source: Path, source_audit: Path, index: Path, directories: list[Path], *, limit=0,
          workers=1):
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("Audit workers must be between 1 and 8")
    proof = json.loads(source_audit.read_text(encoding="utf-8"))
    if proof.get("format") != "malecns-bounds-audit-v1" or digest(source) != proof.get(
        "index_sha256"
    ):
        raise ValueError("Source audit mismatch")
    before = digest(index)
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        rows = src.execute("SELECT body_id, status, sha256 FROM bounds ORDER BY body_id").fetchall()
    if len(rows) != proof.get("verified") or any(row[1] != "ok" for row in rows):
        raise ValueError("Incomplete source")
    pool = (ProcessPoolExecutor(max_workers=workers,
                                mp_context=multiprocessing.get_context("spawn"))
            if workers > 1 else None)
    with (pool or nullcontext()) as executor, \
            sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True) as db:
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        if (
            meta.get("format") != "malecns-segment-rtree-v1"
            or meta.get("source_sha256") != proof["index_sha256"]
            or meta.get("graph_sha256") != proof["graph_sha256"]
            or meta.get("neurons") != str(len(rows))
        ):
            raise ValueError("Index metadata mismatch")
        indexed = db.execute(
            "SELECT ordinal, body_id, sha256, boxes FROM neurons ORDER BY ordinal"
        ).fetchall()
        if (
            len(indexed) != len(rows)
            or db.execute("SELECT rtreecheck('boxes')").fetchone()[0] != "ok"
        ):
            raise ValueError("Incomplete or invalid R-tree")
        total = 0
        pending = []
        for ordinal, (entry, expected) in enumerate(zip(indexed, rows, strict=True)):
            index_ordinal, body, sha, count = entry
            if (index_ordinal, body, sha) != (ordinal, expected[0], expected[2]) or count <= 0:
                raise ValueError("Source identity mismatch")
            box_rows = exact_boxes(db, ordinal, count)
            pending.append((body, sha, directories, box_rows))
            total += count
            end = ordinal + 1 == len(rows) or (limit and ordinal + 1 >= limit)
            if len(pending) >= 16 or end:
                checked = list(executor.map(_check_source, pending) if executor
                               else map(_check_source, pending))
                if checked != [item[0] for item in pending]:
                    raise ValueError("Audit worker returned inconsistent identity")
                pending.clear()
            if (ordinal + 1) % 100 == 0:
                print(f"audited {ordinal + 1}/{len(rows)}", flush=True)
            if limit and ordinal + 1 >= limit:
                return {"partial": ordinal + 1, "expected": len(rows)}
        if db.execute("SELECT count(*) FROM boxes").fetchone()[0] != total:
            raise ValueError("Unexpected boxes")
    if digest(index) != before or digest(source) != proof["index_sha256"]:
        raise ValueError("Index changed during audit")
    return {
        "format": "malecns-segment-audit-v1",
        "verified": len(rows),
        "boxes": total,
        "index_sha256": before,
        "source_sha256": proof["index_sha256"],
        "graph_sha256": proof["graph_sha256"],
        "interpretation": "all source segments enclosed; not excitation",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.report.exists():
        raise SystemExit("Refusing to overwrite audit report")
    result = audit(args.source, args.source_audit, args.index, args.morphology_dir,
                   workers=args.workers)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result), flush=True)
