"""Verify locally acquired MaleCNS source neuropil meshes and report coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.neuropil_mesh import decode_legacy_mesh  # noqa: E402

DATASETS = {"fullbrain-roi-v4", "malecns-vnc-neuropil-roi-v0"}


def audit(root: Path):
    root = root.resolve()
    inventory = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("Empty neuropil inventory")
    seen, summary = set(), []
    for record in inventory:
        dataset, segment = record["dataset"], record["id"]
        if (dataset not in DATASETS or not isinstance(segment, str)
                or not re.fullmatch(r"[1-9]\d*", segment) or (dataset, segment) in seen
                or record["file"] != f"{dataset}/{segment}.ngmesh"
                or not isinstance(record.get("label"), str) or not record["label"]):
            raise ValueError("Invalid neuropil inventory record")
        seen.add((dataset, segment))
        path = root / record["file"]
        if not path.resolve().is_relative_to(root):
            raise ValueError("Neuropil path escapes inventory")
        raw = path.read_bytes()
        fragment, = record["fragments"]
        if (len(raw) != fragment["bytes"] or not re.fullmatch(r"[0-9a-f]{32}", fragment["etag"])
                or hashlib.md5(raw).hexdigest() != fragment["etag"]):
            raise ValueError("Neuropil source size or MD5 mismatch")
        mesh = decode_legacy_mesh(raw, expected_sha256=record["sha256"])
        vertices = mesh["vertices_um"]
        summary.append({"dataset": dataset, "id": segment, "label": record["label"],
                        "sha256": record["sha256"], "vertices": len(vertices),
                        "triangles": len(mesh["faces"]),
                        "bounds_um": [vertices.min(axis=0).tolist(),
                                      vertices.max(axis=0).tolist()]})
    return {"regions": len(summary), "coordinate_frame": "MaleCNS native EM, micrometres",
            "interpretation": "neuropil segmentation; not tissue conductivity or body registration",
            "meshes": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.directory)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"regions": report["regions"],
                      "coordinate_frame": report["coordinate_frame"]}))


if __name__ == "__main__":
    main()
