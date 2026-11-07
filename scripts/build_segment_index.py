"""Build a resumable conservative segment R-tree from an audited bounds snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402
from service.infrastructure.stimulation.segment_bounds import segment_boxes  # noqa: E402


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def build(source: Path, audit: Path, output: Path, directories: list[Path], *, limit=0):
    if output.resolve() == source.resolve() or type(limit) is not int or limit < 0:
        raise ValueError("Invalid index destination or limit")
    proof = json.loads(audit.read_text(encoding="utf-8"))
    if proof.get("format") != "malecns-bounds-audit-v1" or digest(source) != proof.get(
        "index_sha256"
    ):
        raise ValueError("Source index was not independently audited")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as src:
        source_meta = dict(src.execute("SELECT key, value FROM metadata"))
        rows = src.execute("SELECT body_id, status, sha256 FROM bounds ORDER BY body_id").fetchall()
    if (
        len(rows) != proof.get("verified")
        or source_meta.get("graph_sha256") != proof.get("graph_sha256")
        or any(row[1] != "ok" for row in rows)
    ):
        raise ValueError("Source snapshot is incomplete")
    algorithm = hashlib.sha256(
        Path(__file__).read_bytes()
        + Path(sys.modules[segment_boxes.__module__].__file__).read_bytes()
    ).hexdigest()
    meta = {
        "format": "malecns-segment-rtree-v1",
        "source_sha256": proof["index_sha256"],
        "graph_sha256": proof["graph_sha256"],
        "neurons": str(len(rows)),
        "algorithm_sha256": algorithm,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS neurons (ordinal INTEGER PRIMARY KEY, "
            "body_id INTEGER NOT NULL, sha256 TEXT NOT NULL, boxes INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS boxes USING rtree"
            "(id, min_x, max_x, min_y, max_y, min_z, max_z)"
        )
        existing_meta = dict(db.execute("SELECT key, value FROM metadata"))
        if existing_meta and existing_meta != meta:
            raise ValueError("Segment index does not match source or algorithm")
        if not existing_meta:
            db.executemany("INSERT INTO metadata VALUES (?, ?)", meta.items())
            db.commit()
        existing = db.execute(
            "SELECT ordinal, body_id, sha256 FROM neurons ORDER BY ordinal"
        ).fetchall()
        if len(existing) > len(rows) or any(
            row != (i, rows[i][0], rows[i][2]) for i, row in enumerate(existing)
        ):
            raise ValueError("Segment index has inconsistent completed rows")
        done = len(existing)
        for ordinal in range(done, len(rows)):
            body, _, sha = rows[ordinal]
            swc = read_skeleton(body, directories, expected_sha256=sha)["swc"]
            boxes = segment_boxes(swc)
            if len(boxes) >= 2**32:
                raise ValueError("Too many segment boxes")
            db.executemany(
                "INSERT INTO boxes VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        ordinal * 2**32 + i,
                        float(box[0]),
                        float(box[3]),
                        float(box[1]),
                        float(box[4]),
                        float(box[2]),
                        float(box[5]),
                    )
                    for i, box in enumerate(boxes)
                ),
            )
            db.execute("INSERT INTO neurons VALUES (?, ?, ?, ?)", (ordinal, body, sha, len(boxes)))
            if (ordinal + 1) % 100 == 0:
                db.commit()
                print(f"indexed {ordinal + 1}/{len(rows)}", flush=True)
            if limit and ordinal + 1 - done >= limit:
                break
        db.commit()
        finished = db.execute("SELECT count(*) FROM neurons").fetchone()[0]
    if digest(source) != proof["index_sha256"]:
        raise ValueError("Source index changed during build")
    return {"indexed": finished, "expected": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.source, args.audit, args.output, args.morphology_dir, limit=args.limit)
        ),
        flush=True,
    )
