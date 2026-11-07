"""Build resumable conservative per-cell radius bounds for contact screening."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_segment_index import digest  # noqa: E402
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402


def max_swc_radius_um(swc: str) -> float:
    """Return a conservative bound; source radii use MaleCNS 8 nm units."""
    maximum = None
    for line in swc.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) != 7:
            raise ValueError("Malformed SWC")
        radius = float(fields[5]) * 0.008
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("Invalid SWC radius")
        maximum = radius if maximum is None else max(maximum, radius)
    if maximum is None:
        raise ValueError("Empty SWC")
    return maximum


def build(source: Path, audit: Path, output: Path, directories: list[Path], *, limit=0):
    """Use audited bounds IDs and hashes; never infer completeness from a partial index."""
    if source.resolve() == output.resolve() or type(limit) is not int or limit < 0:
        raise ValueError("Invalid index destination or limit")
    proof = json.loads(audit.read_text(encoding="utf-8"))
    if (proof.get("format") != "malecns-bounds-audit-v1"
            or digest(source) != proof.get("index_sha256")):
        raise ValueError("Source bounds audit mismatch")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT body_id, status, sha256 FROM bounds ORDER BY body_id").fetchall()
    if len(rows) != proof.get("verified") or any(row[1] != "ok" for row in rows):
        raise ValueError("Incomplete source bounds")
    meta = {"format": "malecns-radius-bounds-v1", "source_sha256": proof["index_sha256"],
            "graph_sha256": proof["graph_sha256"], "neurons": str(len(rows)),
            "algorithm_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output) as db:
        db.execute("CREATE TABLE IF NOT EXISTS metadata "
                   "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS radii (ordinal INTEGER PRIMARY KEY, "
                   "body_id INTEGER NOT NULL UNIQUE, sha256 TEXT NOT NULL, "
                   "radius_um REAL NOT NULL)")
        stored = dict(db.execute("SELECT key, value FROM metadata"))
        if stored and stored != meta:
            raise ValueError("Radius index belongs to another source")
        if not stored:
            db.executemany("INSERT INTO metadata VALUES (?, ?)", meta.items())
            db.commit()
        existing = db.execute(
            "SELECT ordinal, body_id, sha256 FROM radii ORDER BY ordinal"
        ).fetchall()
        if len(existing) > len(rows) or any(
            entry != (index, rows[index][0], rows[index][2])
            for index, entry in enumerate(existing)
        ):
            raise ValueError("Radius index has inconsistent completed rows")
        done = len(existing)
        for ordinal in range(done, len(rows)):
            body, _, sha = rows[ordinal]
            swc = read_skeleton(body, directories, expected_sha256=sha)["swc"]
            radius = max_swc_radius_um(swc)
            db.execute("INSERT INTO radii VALUES (?, ?, ?, ?)", (ordinal, body, sha, radius))
            if (ordinal + 1) % 500 == 0:
                db.commit()
                print(f"indexed {ordinal + 1}/{len(rows)}", flush=True)
            if limit and ordinal + 1 - done >= limit:
                break
        db.commit()
        completed = db.execute("SELECT count(*) FROM radii").fetchone()[0]
    if digest(source) != proof["index_sha256"]:
        raise ValueError("Source bounds changed during indexing")
    return {"indexed": completed, "expected": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.audit, args.output, args.morphology_dir,
                           limit=args.limit)), flush=True)
