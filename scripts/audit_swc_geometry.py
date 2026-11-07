"""Describe source SWC geometry; do not infer physiological identity or area."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.infrastructure.connectome.morphology_repository import read_skeleton  # noqa: E402


def describe(body_id: int, directories: list[Path]):
    source = read_skeleton(body_id, directories)
    rows = [line.split() for line in source["swc"].splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    nodes = {int(row[0]): (np.asarray([float(value) * .008 for value in row[2:5]]),
                           float(row[5]) * .008, int(row[6])) for row in rows}
    lengths, lateral = [], []
    for xyz, radius, parent in nodes.values():
        if parent == -1:
            continue
        parent_xyz, parent_radius, _ = nodes[parent]
        length = float(np.linalg.norm(xyz - parent_xyz))
        lengths.append(length)
        area = np.pi * (parent_radius + radius) * np.hypot(length, radius - parent_radius)
        lateral.append(float(area))
    return {
        "body_id": source["body_id"], "source_sha256": source["sha256"],
        "source_url": source["source"], "vertices": len(nodes),
        "components": sum(parent == -1 for _, _, parent in nodes.values()),
        "zero_radius_vertices": sum(radius <= 0 for _, radius, _ in nodes.values()),
        "cable_length_um": sum(lengths), "frustum_lateral_area_um2": sum(lateral),
        "limitations": ("SWC radius-derived geometry; excludes soma caps, overlap "
                        "and biological calibration"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--directory", type=Path, action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(describe(args.id, args.directory), allow_nan=False))


if __name__ == "__main__":
    main()
