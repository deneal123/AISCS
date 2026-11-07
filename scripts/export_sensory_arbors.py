"""Export unsimplified, checked central sensory SWC arbors for scene inspection.

Only the registered input populations are included. Original SWC files stay in
the ignored source cache. The resulting geometry does not define a conductor,
an extracellular source model or propagation timing within an individual cell.
"""

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

ANNOTATIONS_SHA = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"
REGION_COUNTS = {
    "head": 1733,
    "notum": 214,
    "front_left": 151,
    "front_right": 115,
    "middle_left": 378,
    "middle_right": 428,
    "hind_left": 394,
    "hind_right": 411,
}


def input_region(row: dict) -> str | None:
    if row["superclass"] == "cb_sensory" and row["class"] == "mechanosensory":
        return "head"
    if row["superclass"] != "vnc_sensory" or row["class"] != "mechanosensory_tactile":
        return None
    if row["entryNerve"] == "PDMN" and row.get("subclass") == "notum":
        return "notum"
    segment = {"ProLN": "front", "MesoLN": "middle", "MetaLN": "hind"}.get(row["entryNerve"])
    side = {"L": "left", "R": "right"}.get(row["rootSide"] or row["somaSide"])
    return f"{segment}_{side}" if segment and side else None


def packed_swc(raw: bytes) -> tuple[bytes, dict]:
    actual = neurite_landmark(raw.decode("utf-8"))  # Includes graph integrity checks.
    rows = [
        line.split()
        for line in raw.decode("utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    rows.sort(key=lambda row: int(row[0]))
    indices = {int(row[0]): i for i, row in enumerate(rows)}
    result = bytearray()
    for row in rows:
        parent = int(row[6])
        result.extend(
            struct.pack(
                "<fffi",
                *(float(v) * 0.008 for v in row[2:5]),
                -1 if parent == -1 else indices[parent],
            )
        )
    return bytes(result), actual


def export_arbors(source: Path, inventory_path: Path, annotations_path: Path, target: Path) -> dict:
    import pyarrow.feather as feather

    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    document = json.loads((source / "landmarks.json").read_text(encoding="utf-8"))
    if (
        inventory["annotations_sha256"] != ANNOTATIONS_SHA
        or document["annotations_sha256"] != ANNOTATIONS_SHA
        or hashlib.sha256(annotations_path.read_bytes()).hexdigest() != ANNOTATIONS_SHA
    ):
        raise ValueError("Unregistered annotation inventory")
    annotations = feather.read_table(annotations_path, columns=["bodyId", "subclass"]).to_pydict()
    subclasses = dict(zip(annotations["bodyId"], annotations["subclass"], strict=True))
    receipts = {row["body_id"]: row for row in document["landmarks"]}
    groups = {name: [] for name in REGION_COUNTS}
    for row in inventory["missing"]:
        region = input_region({**row, "subclass": subclasses.get(row["bodyId"])})
        if region:
            groups[region].append(row["bodyId"])
    if {name: len(ids) for name, ids in groups.items()} != REGION_COUNTS:
        raise ValueError("Incomplete registered sensory populations")
    target.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for region, ids in groups.items():
        binary, cells = bytearray(), []
        for body_id in sorted(ids):
            receipt = receipts[body_id]
            raw = (source / "raw" / f"{body_id}.swc").read_bytes()
            if hashlib.sha256(raw).hexdigest() != receipt["sha256"]:
                raise ValueError("Raw skeleton integrity mismatch")
            packed, actual = packed_swc(raw)
            if actual != {key: receipt[key] for key in actual}:
                raise ValueError("Raw skeleton differs from its checked landmark")
            cells.append(
                {
                    "id": str(body_id),
                    "start": len(binary) // 16,
                    "count": actual["vertices"],
                    "source_sha256": receipt["sha256"],
                }
            )
            binary.extend(packed)
        compressed = gzip.compress(binary, mtime=0)
        filename = f"arbors-{region}.bin.gz"
        (target / filename).write_bytes(compressed)
        bundles[region] = {
            "file": filename,
            "bytes": len(binary),
            "compressed_bytes": len(compressed),
            "sha256": hashlib.sha256(compressed).hexdigest(),
            "cells": cells,
        }
    metadata = {
        "dataset_id": document["dataset_id"],
        "annotations_sha256": ANNOTATIONS_SHA,
        "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "source_page": document["source_page"],
        "source_frame": document["source_frame"],
        "source_url_prefix": document["source"],
        "license": "CC-BY-4.0",
        "units": "um",
        "record_bytes": 16,
        "encoding": "gzip",
        "layout": (
            "little-endian float32 native x/y/z um, "
            "int32 parent row within the cell (-1 root)"
        ),
        "display_embedding": "male-cns-flybody-view-only-v2",
        "method": "all-source-swc-vertices-and-parent-segments-v1",
        "limitations": (
            "Central sensory arbors only; no fabricated peripheral path "
            "or intracellular propagation timing."
        ),
        "neurons": sum(REGION_COUNTS.values()),
        "bundles": bundles,
    }
    (target / "arbors.json").write_text(
        json.dumps(metadata, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "neurons": metadata["neurons"],
        "regions": {
            k: {
                "cells": len(v["cells"]),
                "vertices": v["bytes"] // 16,
                "compressed_bytes": v["compressed_bytes"],
            }
            for k, v in bundles.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    result = export_arbors(args.source, args.inventory, args.annotations, args.target)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
