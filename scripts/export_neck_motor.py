"""Export annotated cervical motor cells without inferring muscle targets."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

SOURCE = "d27d8ed9294b57d28a7c376b0a958fc9074b93ae4ea2ce77441c1c18c1570bee"


def export(source: Path, destination: Path):
    import pyarrow.feather as feather

    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE:
        raise ValueError("Unregistered MaleCNS annotations")
    fields = ["bodyId", "superclass", "exitNerve", "type", "rootSide", "somaSide"]
    table = feather.read_table(source, columns=fields).to_pydict()
    if len(table["bodyId"]) != 166700:
        raise ValueError("Incomplete MaleCNS annotations")
    cells = []
    for row in zip(*(table[name] for name in fields), strict=True):
        body_id, superclass, nerve, cell_type, root_side, soma_side = row
        if nerve == "CvN" and superclass in ("cb_motor", "vnc_motor"):
            cells.append({"id": str(body_id), "superclass": superclass, "type": cell_type,
                          "root_side": root_side, "soma_side": soma_side})
    cells.sort(key=lambda cell: int(cell["id"]))
    counts = dict(Counter(cell["superclass"] for cell in cells))
    if len(cells) != 24 or counts != {"cb_motor": 20, "vnc_motor": 4}:
        raise ValueError("Unexpected cervical motor population")
    document = {
        "version": "male-cns-cvn-motor-v1",
        "dataset_id": "male-cns:v1.0-annotated-nonglial",
        "annotations_sha256": SOURCE,
        "nerve": "CvN",
        "cells": cells,
        "counts": counts,
        "limitations": (
            "No inferred muscle target, laterality or motion; "
            "CvN is not the complete neck motor system."
        ),
    }
    destination.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(json.dumps({"cells": len(cells), "sha256": checksum}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    export(args.annotations, args.target)
