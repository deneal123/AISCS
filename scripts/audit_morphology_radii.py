"""Independently verify every conservative radius against its source SWC."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_segment_index import digest  # noqa: E402
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402


def audit(source: Path, source_audit: Path, index: Path, directories: list[Path], *, limit=0):
    """Verify every indexed value and identity; partial audits never produce approval."""
    if type(limit) is not int or limit < 0:
        raise ValueError("Invalid audit limit")
    proof = json.loads(source_audit.read_text(encoding="utf8"))
    if (proof.get("format") != "malecns-bounds-audit-v1"
            or digest(source) != proof.get("index_sha256")):
        raise ValueError("Source audit mismatch")
    before = digest(index)
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT body_id, status, sha256 FROM bounds ORDER BY body_id").fetchall()
    if len(rows) != proof.get("verified") or any(row[1] != "ok" for row in rows):
        raise ValueError("Incomplete source bounds")
    with sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True) as db:
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        if (meta.get("format") != "malecns-radius-bounds-v1"
                or meta.get("source_sha256") != proof["index_sha256"]
                or meta.get("graph_sha256") != proof["graph_sha256"]
                or meta.get("neurons") != str(len(rows))
                or not re.fullmatch(r"[a-f0-9]{64}", meta.get("algorithm_sha256", ""))
                or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"):
            raise ValueError("Invalid radius index metadata")
        indexed = db.execute(
            "SELECT ordinal, body_id, sha256, radius_um FROM radii ORDER BY ordinal"
        ).fetchall()
    if len(indexed) != len(rows):
        raise ValueError("Incomplete radius index")
    for ordinal, (item, source_row) in enumerate(zip(indexed, rows, strict=True)):
        position, body, sha, radius = item
        if ((position, body, sha) != (ordinal, source_row[0], source_row[2])
                or type(radius) not in (int, float) or not math.isfinite(radius) or radius < 0):
            raise ValueError("Invalid radius source identity")
        swc = read_skeleton(body, directories, expected_sha256=sha)["swc"]
        values = []
        for line in swc.splitlines():
            fields = line.split()
            if not fields or fields[0].startswith("#"):
                continue
            if len(fields) != 7:
                raise ValueError("Malformed SWC")
            value = float(fields[5]) * 0.008
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid radius")
            values.append(value)
        if (not values or radius < max(values)
                or not math.isclose(radius, max(values), abs_tol=1e-12)):
            raise ValueError("Radius bound differs from source")
        if (ordinal + 1) % 500 == 0:
            print(f"audited {ordinal + 1}/{len(rows)}", flush=True)
        if limit and ordinal + 1 >= limit:
            return {"partial": ordinal + 1, "expected": len(rows)}
    if digest(index) != before or digest(source) != proof["index_sha256"]:
        raise ValueError("Index changed during audit")
    return {"format": "malecns-radius-audit-v1", "verified": len(rows),
            "index_sha256": before, "source_sha256": proof["index_sha256"],
            "graph_sha256": proof["graph_sha256"],
            "interpretation": "radius bounds only; not tissue registration or activation"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--morphology-dir", type=Path, action="append", required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise SystemExit("Refusing to overwrite audit report")
    result = audit(args.source, args.source_audit, args.index, args.morphology_dir)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result), flush=True)
