"""Resume the original segment R-tree using parallel source processing."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import build_segment_index  # noqa: E402
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402
from service.infrastructure.stimulation import segment_bounds  # noqa: E402


def _compute(item):
    ordinal, body, sha, directories = item
    skeleton = read_skeleton(body, directories, expected_sha256=sha)
    return ordinal, body, sha, segment_bounds.segment_boxes(skeleton["swc"])


def resume(source: Path, audit: Path, output: Path, directories: list[Path], *, workers=4, limit=0):
    if (
        type(workers) is not int
        or not 1 <= workers <= 8
        or type(limit) is not int
        or limit < 0
        or output.resolve() == source.resolve()
        or not output.is_file()
    ):
        raise ValueError("Invalid resume settings")
    proof = json.loads(audit.read_text(encoding="utf-8"))
    if proof.get("format") != "malecns-bounds-audit-v1" or build_segment_index.digest(
        source
    ) != proof.get("index_sha256"):
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
        Path(build_segment_index.__file__).read_bytes() + Path(segment_bounds.__file__).read_bytes()
    ).hexdigest()
    expected = {
        "format": "malecns-segment-rtree-v1",
        "source_sha256": proof["index_sha256"],
        "graph_sha256": proof["graph_sha256"],
        "neurons": str(len(rows)),
        "algorithm_sha256": algorithm,
    }
    with sqlite3.connect(output, timeout=1) as db:
        if dict(db.execute("SELECT key, value FROM metadata")) != expected:
            raise ValueError("Segment index does not match source or algorithm")
        existing = db.execute(
            "SELECT ordinal, body_id, sha256 FROM neurons ORDER BY ordinal"
        ).fetchall()
        if len(existing) > len(rows) or any(
            row != (i, rows[i][0], rows[i][2]) for i, row in enumerate(existing)
        ):
            raise ValueError("Segment index has inconsistent completed rows")
        done = len(existing)
        end = min(len(rows), done + limit) if limit else len(rows)
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            for start in range(done, end, 32):
                tasks = [
                    (i, rows[i][0], rows[i][2], directories)
                    for i in range(start, min(start + 32, end))
                ]
                computed = list(pool.map(_compute, tasks, chunksize=2))
                for ordinal, body, sha, boxes in computed:
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
                    db.execute(
                        "INSERT INTO neurons VALUES (?, ?, ?, ?)", (ordinal, body, sha, len(boxes))
                    )
                db.commit()
                print(f"indexed {min(start + 32, end)}/{len(rows)}", flush=True)
    if build_segment_index.digest(source) != proof["index_sha256"]:
        raise ValueError("Source index changed during build")
    return {"indexed": end, "expected": len(rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    print(
        json.dumps(
            resume(
                args.source,
                args.audit,
                args.output,
                args.morphology_dir,
                workers=args.workers,
                limit=args.limit,
            )
        ),
        flush=True,
    )
