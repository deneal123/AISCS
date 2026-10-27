"""Derive view-only limb routes from the pinned Apache-2.0 FlyBody asset.

This does not reconstruct axons or alter the numerical recording geometry.
Run in the generator environment; supply the immutable frontend asset directory.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def derive(root: Path) -> dict:
    scene_bytes, binary = (root / "scene.json").read_bytes(), (root / "scene.bin").read_bytes()
    if (
        hashlib.sha256(scene_bytes).hexdigest()
        != "8eb70a265a179e811c902fda4334aa83bc34f54a58d400db0c3a6f98ccbd62dd"
    ):
        raise ValueError("Unregistered FlyBody metadata")
    if (
        hashlib.sha256(binary).hexdigest()
        != "263eaa17551e807e541937a6e9f9267b9f9836a89f6b15300fff06f332f71782"
    ):
        raise ValueError("Unregistered FlyBody mesh")
    scene, routes = json.loads(scene_bytes), {}
    for segment, label in (("T1", "front"), ("T2", "middle"), ("T3", "hind")):
        for side in ("left", "right"):
            parts = [p for p in scene["parts"] if p.get("leg_root") == f"coxa_{segment}_{side}"]
            coxa = next(p for p in parts if p["name"] == f"coxa_{segment}_{side}")
            start = np.asarray(coxa["pivot_mm"])
            path, previous = [start * [1, 0, 1], start], start
            for stem in (
                "coxa",
                "femur",
                "tibia",
                "tarsus",
                "tarsus2",
                "tarsus3",
                "tarsus4",
                "tarsus5",
            ):
                part = next((p for p in parts if p["name"] == f"{stem}_{segment}_{side}"), None)
                if part is None:
                    continue
                layout = part["positions"]
                points = np.frombuffer(
                    binary, dtype="<f4", count=layout["count"], offset=layout["byte_offset"]
                ).reshape(-1, 3)
                center = points.mean(axis=0)
                _, vectors = np.linalg.eigh(np.cov((points - center).T))
                axis = vectors[:, -1]
                projection = (points - center) @ axis
                first = center + axis * np.percentile(projection, 8)
                last = center + axis * np.percentile(projection, 92)
                if np.linalg.norm(first - previous) > np.linalg.norm(last - previous):
                    first, last = last, first
                path.extend([first, last])
                previous = last
            path = (
                [path[0], path[1]]
                + [(path[i] + path[i + 1]) / 2 for i in range(3, len(path) - 1, 2)]
                + [path[-1]]
            )
            routes[label + "_" + side] = np.round(path, 6).tolist()
    return {
        "asset_id": "flybody-sim003-fdbbd866-rest-v1",
        "asset_sha256": hashlib.sha256(scene_bytes).hexdigest(),
        "license": "Apache-2.0",
        "source": "https://github.com/google-deepmind/mujoco_menagerie/tree/f3b6013629c7b94f8ee93fd977b161fa8350f9bc/flybody",
        "method": (
            "View-only PCA centre-lines of rest-pose limb meshes, joint midpoints; "
            "not reconstructed peripheral axons."
        ),
        "routes": routes,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "service/infrastructure/connectome/body-routes.json",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    record = derive(args.asset_root)
    if args.check:
        if json.loads(args.output.read_text()) != record:
            raise SystemExit("Body route derivative differs")
        print("Six registered view-only body routes match the pinned asset")
    else:
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
