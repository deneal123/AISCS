"""Export exact-ID motor populations; no muscle mechanics are inferred."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ANNOTATIONS_SHA256 = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"
NERVES = {"ProLN": ("front", "T1"), "MesoLN": ("middle", "T2"), "MetaLN": ("hind", "T3")}


def motor_population(row):
    if row["superclass"] != "vnc_motor" or row["exitNerve"] not in NERVES:
        return None
    prefix, segment = NERVES[row["exitNerve"]]
    if row["somaSide"] not in ("L", "R") or row["somaNeuromere"] != segment:
        raise ValueError("Inconsistent motor population annotation")
    return prefix + "_" + {"L": "left", "R": "right"}[row["somaSide"]]


def export_motor(annotations: Path, target: Path):
    import pyarrow.feather as feather

    if hashlib.sha256(annotations.read_bytes()).hexdigest() != ANNOTATIONS_SHA256:
        raise ValueError("Unregistered annotation file")
    data = feather.read_table(annotations).to_pydict()
    if len(data["bodyId"]) != 166700:
        raise ValueError("Incomplete registered graph")
    rows = []
    for i in range(len(data["bodyId"])):
        row = {key: data[key][i] for key in data}
        region = motor_population(row)
        if region:
            rows.append(
                {
                    "id": str(row["bodyId"]),
                    "region": region,
                    "type": row["type"],
                    "exit_nerve": row["exitNerve"],
                    "soma_side": row["somaSide"],
                    "neuromere": row["somaNeuromere"],
                }
            )
    rows.sort(key=lambda row: int(row["id"]))
    counts = dict(Counter(row["region"] for row in rows))
    if len(rows) != 319 or sorted(counts.values()) != [40, 41, 58, 58, 60, 62]:
        raise ValueError("Unexpected registered motor coverage")
    manifest = {
        "version": "male-cns-motor-display-v1",
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "annotations_sha256": ANNOTATIONS_SHA256,
        "source": "https://male-cns.janelia.org/download/",
        "license": "CC BY 4.0",
        "selection": "vnc_motor; exitNerve ProLN/MesoLN/MetaLN; matching somaNeuromere",
        "laterality": "somaSide; not an independently validated peripheral muscle map",
        "neurons": len(rows),
        "counts": counts,
        "cells": rows,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return {
        "neurons": len(rows),
        "counts": counts,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_motor(args.annotations, args.target)))


if __name__ == "__main__":
    main()
