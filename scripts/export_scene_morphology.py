"""Publish a compact, checked scene asset from downloaded MaleCNS skeletons."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.morphology import neurite_landmark  # noqa: E402


def export_scene(source: Path, target: Path, inventory_path: Path) -> dict:
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    document = json.loads((source / "landmarks.json").read_text(encoding="utf-8"))
    records = sorted(document.pop("landmarks"), key=lambda row: row["body_id"])
    if document["annotations_sha256"] != inventory["annotations_sha256"]:
        raise ValueError("Mismatched annotation inventory")
    if any("errors" in row for row in records):
        raise ValueError("Unresolved skeletons; do not publish a complete-coverage asset")
    if len({row["body_id"] for row in records}) != len(records):
        raise ValueError("Duplicate body identity")
    if {row["body_id"] for row in records} != {row["bodyId"] for row in inventory["missing"]}:
        raise ValueError("Incomplete or unrelated neuron coverage")
    binary, receipts = bytearray(), []
    for row in records:
        raw = (source / "raw" / f"{row['body_id']}.swc").read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Skeleton integrity mismatch")
        actual = neurite_landmark(raw.decode("utf-8"))
        if actual != {key: row[key] for key in actual}:
            raise ValueError("Landmark differs from the source reconstruction")
        binary.extend(struct.pack("<QfffI", row["body_id"], *row["anchor_um"], row["swc_vertex"]))
        receipts.append(json.dumps(row, sort_keys=True, separators=(",", ":")))
    provenance = gzip.compress(("\n".join(receipts) + "\n").encode(), mtime=0)
    metadata = {
        **document,
        "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "count": len(records),
        "method": "nearest-swc-vertex-to-cable-centroid-v1",
        "semantics": "An actual neurite vertex, not an estimated soma or electrical source",
        "display_embedding": "male-cns-flybody-view-only-v2",
        "binary": {
            "file": "landmarks.bin",
            "record_bytes": 24,
            "layout": "little-endian uint64 bodyId, float32 x/y/z um, uint32 SWC vertex",
            "bytes": len(binary),
            "sha256": hashlib.sha256(binary).hexdigest(),
        },
        "receipts": {
            "file": "landmarks.sources.jsonl.gz",
            "bytes": len(provenance),
            "sha256": hashlib.sha256(provenance).hexdigest(),
        },
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / "landmarks.bin").write_bytes(binary)
    (target / "landmarks.sources.jsonl.gz").write_bytes(provenance)
    # Metadata is published last; an interrupted export cannot advertise new bytes.
    (target / "landmarks.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_scene(args.source, args.target, args.inventory), indent=2))


if __name__ == "__main__":
    main()
