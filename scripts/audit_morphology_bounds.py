"""Independently compare an entire completed bounds index with its SWC sources.

The audit establishes agreement while it runs; it cannot guarantee source files
remain unchanged afterwards. It never upgrades a partial index to complete.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_morphology_bounds import MANIFEST_SHA256, SCHEMA, registered_ids  # noqa: E402

BASE = "https://storage.googleapis.com/flyem-male-cns/v1.0/segmentation/skeletons-malecns/skeletons-swc/"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def independently_read_bounds(body_id: int, sha: str, directories: list[Path]):
    """Verify raw bytes and derive extrema without the indexing parser."""
    for directory in directories:
        raw = directory / "raw" / f"{body_id}.swc"
        receipt = directory / "receipts" / f"{body_id}.json"
        if not raw.is_file() or not receipt.is_file():
            continue
        try:
            if raw.stat().st_size > 8 * 1024 * 1024:
                continue
            data = raw.read_bytes()
            meta = json.loads(receipt.read_text(encoding="utf-8"))
            if (not isinstance(meta, dict) or hashlib.sha256(data).hexdigest() != sha
                    or meta.get("sha256") != sha
                    or meta.get("body_id") != body_id
                    or meta.get("url") != BASE + f"{body_id}.swc"):
                continue
            lows, highs = [math.inf] * 3, [-math.inf] * 3
            count = 0
            for line in data.decode("utf-8").splitlines():
                row = line.strip()
                if not row or row.startswith("#"):
                    continue
                fields = row.split()
                if len(fields) != 7:
                    raise ValueError("Malformed SWC")
                for axis, field in enumerate(fields[2:5]):
                    value = float(field) * .008
                    if not math.isfinite(value):
                        raise ValueError("Non-finite coordinate")
                    lows[axis] = min(lows[axis], value)
                    highs[axis] = max(highs[axis], value)
                count += 1
            if not count:
                raise ValueError("Empty SWC")
            return [value for axis in range(3) for value in (lows[axis], highs[axis])]
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            continue
    raise ValueError(f"Source or receipt mismatch for neuron {body_id}")


def _audit_row(item):
    expected, row, directories = item
    if row[0] != expected or row[1] != "ok" or not isinstance(row[2], str):
        raise ValueError("Index incomplete or source unavailable")
    if independently_read_bounds(expected, row[2], directories) != list(row[3:]):
        raise ValueError(f"Bounding box mismatch for neuron {expected}")
    return expected


def audit(database: Path, ids, graph_sha: str, directories: list[Path], *, progress=None,
          workers=1):
    """Compare every graph ID and source; fail on partial or changing index."""
    if type(workers) is not int or workers < 1:
        raise ValueError("Workers must be a positive integer")
    before = digest(database)
    pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
    with (pool or nullcontext()) as executor, \
            sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if (metadata.get("format") != SCHEMA or metadata.get("graph_sha256") != graph_sha
                or metadata.get("neurons") != str(len(ids))):
            raise ValueError("Index provenance mismatch")
        rows = db.execute("SELECT body_id, status, sha256, min_x, max_x, min_y, max_y, "
                          "min_z, max_z FROM bounds ORDER BY body_id")
        count = 0
        while count < len(ids):
            batch = rows.fetchmany(min(256, len(ids) - count))
            if not batch:
                raise ValueError("Index incomplete")
            entries = [(ids[count + i], row, directories) for i, row in enumerate(batch)]
            checked = executor.map(_audit_row, entries) if executor else map(_audit_row, entries)
            for _ in checked:
                count += 1
                if progress and count % 500 == 0:
                    progress(count, len(ids))
        if rows.fetchone() is not None:
            raise ValueError("Index has extra neurons")
    if count != len(ids) or digest(database) != before:
        raise ValueError("Index incomplete or changed during audit")
    return {"format": "malecns-bounds-audit-v1", "verified": count,
            "index_sha256": before, "graph_sha256": graph_sha,
            "interpretation": "source snapshot checked during audit; no excitation inferred"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    ids = registered_ids(args.graph)
    result = audit(args.index, ids, MANIFEST_SHA256, args.morphology_dir,
                   progress=lambda done, total: print(f"audited {done}/{total}", flush=True),
                   workers=args.workers)
    with args.report.open("x", encoding="utf-8", newline="\n") as report:
        report.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
