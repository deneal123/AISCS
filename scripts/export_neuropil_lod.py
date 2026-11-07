"""Create a view-only, bounded-error approximation of source neuropil surfaces."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.audit_neuropil import audit  # noqa: E402
from service.infrastructure.connectome.dataset import MANIFEST_SHA256  # noqa: E402
from service.infrastructure.connectome.neuropil_mesh import decode_legacy_mesh  # noqa: E402


def cluster_surface(vertices: np.ndarray, faces: np.ndarray, grid_um: float):
    """Merge vertices within fixed cubes and retain nondegenerate source faces."""
    if not np.isfinite(grid_um) or not 0 < grid_um <= 10:
        raise ValueError("Invalid visual grid")
    cells = np.floor(vertices / grid_um).astype(np.int64)
    _, inverse, counts = np.unique(cells, axis=0, return_inverse=True, return_counts=True)
    centers = np.column_stack([
        np.bincount(inverse, weights=vertices[:, axis]) / counts for axis in range(3)
    ])
    mapped = inverse[faces]
    nondegenerate = ((mapped[:, 0] != mapped[:, 1]) & (mapped[:, 0] != mapped[:, 2])
                     & (mapped[:, 1] != mapped[:, 2]))
    mapped = mapped[nondegenerate]
    _, unique = np.unique(np.sort(mapped, axis=1), axis=0, return_index=True)
    mapped = mapped[np.sort(unique)]
    if not len(mapped):
        raise ValueError("Visual mesh contains no triangles")
    displacement = np.linalg.norm(vertices - centers[inverse], axis=1).max()
    if displacement > np.sqrt(3) * grid_um + 1e-9:
        raise ValueError("Visual mesh exceeds displacement bound")
    return centers.astype("<f4"), mapped.astype("<u4"), float(displacement)


def export(source: Path, output: Path, grid_um: float):
    report = audit(source)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "manifest.json").exists():
        raise ValueError("Output already contains a published generation")
    meshes = []
    for record in report["meshes"]:
        raw = (source / record["dataset"] / f"{record['id']}.ngmesh").read_bytes()
        original = decode_legacy_mesh(raw, expected_sha256=record["sha256"])
        vertices, faces, error = cluster_surface(
            original["vertices_um"], original["faces"], grid_um
        )
        data = struct.pack("<II", len(vertices), len(faces)) + vertices.tobytes() + faces.tobytes()
        compressed = gzip.compress(data, compresslevel=6, mtime=0)
        file = f"{record['dataset']}-{record['id']}.bin.gz"
        target = output / file
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(compressed)
        temporary.replace(target)
        meshes.append({"id": record["id"], "dataset": record["dataset"], "label": record["label"],
                       "file": file, "source_sha256": record["sha256"],
                       "sha256": hashlib.sha256(compressed).hexdigest(), "bytes": len(compressed),
                       "vertices": len(vertices), "triangles": len(faces),
                       "max_vertex_displacement_um": error})
    manifest = {"dataset_id": "male-cns:v1.0-annotated-nonglial",
                "manifest_sha256": MANIFEST_SHA256,
                "source_frame": "MaleCNS native unmirrored EM", "units": "um",
                "method": "vertex-grid-visual-lod-v1", "grid_um": grid_um,
                "interpretation": ("segmented neuropil, not conductivity or "
                                   "anatomical body registration"),
                "meshes": meshes}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grid-um", type=float, default=3.0)
    args = parser.parse_args()
    result = export(args.source, args.output, args.grid_um)
    print(json.dumps({"regions": len(result["meshes"]),
                      "bytes": sum(item["bytes"] for item in result["meshes"]),
                      "max_error_um": max(item["max_vertex_displacement_um"]
                                          for item in result["meshes"])}))


if __name__ == "__main__":
    main()
