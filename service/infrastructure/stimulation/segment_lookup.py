"""Use a fully audited segment R-tree only as a conservative source filter."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def _local_snapshot(source: Path, expected: str, directory: Path) -> Path:
    """Keep a content-verified snapshot on local storage.

    The source is an independently audited snapshot, not a live mutable index.
    Existing local bytes are verified by segment_ordinals before and after use.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"segments-{expected}.sqlite"
    if target.is_file():
        return target
    temporary = None
    try:
        with source.open("rb") as original, tempfile.NamedTemporaryFile(
            dir=directory, prefix=".segments-", suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            for data in iter(lambda: original.read(1024 * 1024), b""):
                digest.update(data)
                output.write(data)
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected:
            raise ValueError("Segment source changed since audit")
        os.replace(temporary, target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def segment_ordinals(index: Path, audit: Path, *, source_sha: str, graph_sha: str,
                     count: int, contacts, radius_um: float, return_digest: bool = False):
    """Return all potentially matching graph ordinals, rejecting incomplete snapshots."""
    if type(return_digest) is not bool:
        raise ValueError("Invalid digest option")
    try:
        proof = json.loads(audit.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Segment audit unavailable") from exc
    if (not isinstance(proof, dict) or proof.get("format") != "malecns-segment-audit-v1"
            or type(proof.get("verified")) is not int or proof["verified"] != count
            or proof.get("source_sha256") != source_sha or proof.get("graph_sha256") != graph_sha
            or not isinstance(proof.get("index_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", proof["index_sha256"])):
        raise ValueError("Segment audit does not match source")
    cache_dir = os.environ.get("GENERATOR_SEGMENT_SNAPSHOT_DIR")
    if cache_dir:
        index = _local_snapshot(index, proof["index_sha256"], Path(cache_dir))
    if _digest(index) != proof["index_sha256"]:
        raise ValueError("Segment index changed since audit")
    result = set()
    with sqlite3.connect(index.resolve().as_uri() + "?mode=ro", uri=True) as db:
        meta = dict(db.execute("SELECT key, value FROM metadata"))
        if (meta.get("format") != "malecns-segment-rtree-v1"
                or meta.get("source_sha256") != source_sha or meta.get("graph_sha256") != graph_sha
                or meta.get("neurons") != str(count)):
            raise ValueError("Segment index metadata mismatch")
        for x, y, z in contacts:
            values = (x + radius_um, x - radius_um, y + radius_um, y - radius_um,
                      z + radius_um, z - radius_um)
            matches = db.execute("SELECT DISTINCT id / 4294967296 FROM boxes WHERE "
                                 "min_x<=? AND max_x>=? AND min_y<=? AND max_y>=? "
                                 "AND min_z<=? AND max_z>=?", values)
            result.update(row[0] for row in matches)
    if any(type(value) is not int or not 0 <= value < count for value in result):
        raise ValueError("Segment index contains invalid ordinal")
    if _digest(index) != proof["index_sha256"]:
        raise ValueError("Segment index changed during query")
    return (result, proof["index_sha256"]) if return_digest else result
