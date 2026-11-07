"""Build a resumable, source-verified MaleCNS morphology bounding-box snapshot.

Boxes are conservative geometry filters, not electrical activation estimates.
The snapshot reflects source bytes at indexing time; candidates must be
reverified before use, and later source changes require rebuilding the index.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402

from service.infrastructure.connectome import morphology, morphology_repository  # noqa: E402
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402

SCHEMA = "malecns-verified-bounds-v1"
MANIFEST_SHA256 = "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2"


def registered_ids(graph: Path):
    """Verify the registered ID array before indexing any source."""
    manifest_bytes = (graph / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_SHA256:
        raise ValueError("Graph manifest does not match the registered generation")
    manifest = json.loads(manifest_bytes)
    id_bytes = (graph / "ids.npy").read_bytes()
    if hashlib.sha256(id_bytes).hexdigest() != manifest["arrays"]["ids.npy"]:
        raise ValueError("Graph neuron IDs do not match the registered manifest")
    ids = np.load(io.BytesIO(id_bytes), allow_pickle=False)
    if (ids.ndim != 1 or ids.dtype.kind not in "iu" or len(ids) != 166700
            or np.any(ids <= 0) or np.any(np.diff(ids) <= 0)):
        raise ValueError("Malformed registered neuron ID array")
    return [int(value) for value in ids]


def build_index(ids, directories, database: Path, graph_sha: str, *, limit=0):
    """Add verified rows in graph order; keep explicit missing/invalid outcomes."""
    if type(limit) is not int or limit < 0 or not ids or any(
        type(value) is not int or value <= 0 for value in ids
    ) or any(left >= right for left, right in zip(ids, ids[1:], strict=False)):
        raise ValueError("Invalid index inputs")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE IF NOT EXISTS metadata "
                   "(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS bounds (
            body_id INTEGER PRIMARY KEY, status TEXT NOT NULL, sha256 TEXT,
            min_x REAL, max_x REAL, min_y REAL, max_y REAL, min_z REAL, max_z REAL)""")
        algorithm = hashlib.sha256()
        paths = (Path(__file__), Path(morphology.__file__), Path(morphology_repository.__file__))
        for path in paths:
            algorithm.update(path.name.encode() + b"\0" + path.read_bytes())
        expected = {"format": SCHEMA, "graph_sha256": graph_sha, "neurons": str(len(ids)),
                    "algorithm_sha256": algorithm.hexdigest(), "python": sys.version.split()[0],
                    "numpy": np.__version__}
        stored = dict(db.execute("SELECT key, value FROM metadata"))
        if stored and stored != expected:
            raise ValueError("Index belongs to another graph or schema")
        if not stored:
            db.executemany("INSERT INTO metadata VALUES (?, ?)", expected.items())
            db.commit()
        existing = {row[0] for row in db.execute("SELECT body_id FROM bounds")}
        if not existing.issubset(set(ids)):
            raise ValueError("Index contains an unregistered neuron")
        processed = 0
        for body_id in ids:
            if body_id in existing:
                continue
            try:
                result = read_skeleton(body_id, directories)
                bounds = result["bounds_um"]
                row = (body_id, "ok", result["sha256"],
                       *(value for axis in bounds for value in axis))
            except FileNotFoundError:
                row = (body_id, "source_missing", None, *([None] * 6))
            except (ValueError, OSError):
                row = (body_id, "invalid_source", None, *([None] * 6))
            db.execute("INSERT INTO bounds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            processed += 1
            if processed % 500 == 0:
                db.commit()
                print(f"indexed {len(existing) + processed}/{len(ids)}", flush=True)
            if limit and processed >= limit:
                break
        db.commit()
        rows = db.execute("SELECT status, count(*) FROM bounds GROUP BY status").fetchall()
        return {"processed_now": processed, "statuses": dict(rows), "expected": len(ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    ids = registered_ids(args.graph)
    result = build_index(ids, args.morphology_dir, args.output, MANIFEST_SHA256, limit=args.limit)
    print(result, flush=True)


if __name__ == "__main__":
    main()
