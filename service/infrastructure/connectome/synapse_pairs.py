"""Bounded extraction of source synapse locations from the MaleCNS pair table.

Coordinates remain in the native 8 nm EM frame. A pair is an anatomical
observation, not a path for an animated impulse or a body registration.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.ipc as ipc

FIELDS = ("body_pre", "body_post", "x_pre", "y_pre", "z_pre", "x_post", "y_post", "z_post")


def extract_pairs(
    path: Path, body_id: int, expected_md5: str, *, direction: str, limit: int = 10000
):
    """Scan Arrow batches without retaining the full source file in memory.

    The cap affects returned rows only; `total` counts all matches. The digest
    must originate from the pinned source receipt, never a client-provided file.
    """
    if type(body_id) is not int or body_id <= 0 or body_id >= 2**63:
        raise ValueError("Invalid neuron ID")
    if direction not in {"incoming", "outgoing"}:
        raise ValueError("Invalid direction")
    if type(limit) is not int or not 1 <= limit <= 10000:
        raise ValueError("Invalid row limit")
    if len(expected_md5) != 32 or any(c not in "0123456789abcdef" for c in expected_md5):
        raise ValueError("Invalid source checksum")
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_md5:
        raise ValueError("Source checksum mismatch")
    rows, total = [], 0
    with pa.memory_map(str(path), "r") as source:
        reader = ipc.open_file(source)
        if not set(FIELDS).issubset(reader.schema.names):
            raise ValueError("Source schema is incomplete")
        selected_column = "body_pre" if direction == "outgoing" else "body_post"
        for index in range(reader.num_record_batches):
            batch = reader.get_batch(index).select(FIELDS)
            matching = batch.filter(pc.equal(batch.column(selected_column), body_id))
            total += matching.num_rows
            remaining = limit - len(rows)
            if remaining > 0:
                for row in matching.slice(0, remaining).to_pylist():
                    if any(type(row[field]) is not int for field in FIELDS):
                        raise ValueError("Invalid or missing synapse coordinate")
                    rows.append(row)
    return {"body_id": str(body_id), "direction": direction, "total": total,
            "returned": len(rows), "truncated": total > len(rows), "source_md5": expected_md5,
            "coordinate_frame": "male-cns-v1.0-native-8nm", "pairs": rows}
