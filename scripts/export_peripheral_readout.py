"""Exact-ID peripheral nerve readout; its display corridors are not traced axons."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ANNOTATIONS = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"
NERVES = {"ProLN": ("front", "T1"), "MesoLN": ("middle", "T2"), "MetaLN": ("hind", "T3")}


def peripheral_group(row):
    superclass = row["superclass"]
    if superclass in ("cb_sensory", "cb_motor"):
        return "head", "sensory" if superclass == "cb_sensory" else "motor", "head aggregate"
    if superclass not in ("vnc_sensory", "vnc_motor"):
        return None
    sensory = superclass == "vnc_sensory"
    nerve = row["entryNerve" if sensory else "exitNerve"] or ""
    role = "sensory" if sensory else "motor"
    if nerve.startswith("AbN"):
        return "abdomen", role, "abdominal nerve aggregate; target segment not assigned"
    if not sensory and nerve == "CvN":
        return "head", role, "cervical nerve"
    if nerve not in NERVES:
        return None
    side = row["rootSide"] if sensory else row["somaSide"]
    if side not in ("L", "R"):
        return None
    prefix, segment = NERVES[nerve]
    if not sensory and row["somaNeuromere"] != segment:
        raise ValueError("Inconsistent leg motor segment")
    return (
        prefix + "_" + {"L": "left", "R": "right"}[side],
        role,
        ("rootSide" if sensory else "somaSide; muscle-target side not verified"),
    )


def export(annotations: Path, target: Path):
    import pyarrow.feather as feather

    if hashlib.sha256(annotations.read_bytes()).hexdigest() != ANNOTATIONS:
        raise ValueError("Unregistered annotation source")
    fields = [
        "bodyId",
        "superclass",
        "entryNerve",
        "exitNerve",
        "rootSide",
        "somaSide",
        "somaNeuromere",
    ]
    table = feather.read_table(annotations, columns=fields).to_pydict()
    if len(table["bodyId"]) != 166700:
        raise ValueError("Incomplete registered source")
    rows = []
    for i, body_id in enumerate(table["bodyId"]):
        row = {key: values[i] for key, values in table.items()}
        group = peripheral_group(row)
        if group:
            region, role, basis = group
            nerve = row["entryNerve" if role == "sensory" else "exitNerve"]
            rows.append([str(body_id), region, role, nerve, basis])
    rows.sort(key=lambda row: int(row[0]))
    counts = dict(sorted(Counter(row[1] + ":" + row[2] for row in rows).items()))
    manifest = {
        "version": "male-cns-peripheral-readout-v1",
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "annotations_sha256": ANNOTATIONS,
        "source": "https://male-cns.janelia.org/download/",
        "license": "CC BY 4.0",
        "rows_layout": ["body_id", "region", "role", "source_nerve", "grouping_basis"],
        "count": len(rows),
        "counts": counts,
        "rows": rows,
        "limitations": [
            "Display paths follow body corridors, not reconstructed peripheral axons.",
            "Whole-bundle highlighting follows saved events; "
            "peripheral conduction is not calculated.",
            "Head/abdomen are aggregates; no muscle action inferred.",
        ],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "count": len(rows),
        "counts": counts,
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.annotations, args.target)))
