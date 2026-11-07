"""Inventory missing MaleCNS landmarks from the registered annotation file."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pyarrow.feather as feather

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.dataset import ANNOTATIONS_SHA256, digest  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.annotations) != ANNOTATIONS_SHA256:
        raise ValueError("Unregistered MaleCNS annotation file")
    table = feather.read_table(args.annotations)
    info = table.to_pydict()
    missing = [
        i
        for i, (soma, root) in enumerate(
            zip(info["somaLocation"], info["tosomaLocation"], strict=True)
        )
        if soma is None and root is None
    ]
    fields = [
        "bodyId",
        "superclass",
        "class",
        "type",
        "entryNerve",
        "exitNerve",
        "somaNeuromere",
        "rootSide",
        "somaSide",
    ]
    data = {
        "annotations_sha256": ANNOTATIONS_SHA256,
        "schema": str(table.schema),
        "columns": table.column_names,
        "missing_count": len(missing),
        "missing_superclass": dict(Counter(info["superclass"][i] for i in missing)),
        "missing": [{key: info[key][i] for key in fields} for i in missing],
    }
    if len(info["bodyId"]) != 166700 or len(missing) != 26062:
        raise ValueError("Unexpected registered annotation coverage")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Missing-coordinate inventory: {len(missing)} exact MaleCNS body IDs")


if __name__ == "__main__":
    main()
