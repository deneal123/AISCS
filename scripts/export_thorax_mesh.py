"""Extract the registered indexed thorax for server-side anchor checks."""

import argparse
import hashlib
import json
from pathlib import Path

SCENE_SHA = "8eb70a265a179e811c902fda4334aa83bc34f54a58d400db0c3a6f98ccbd62dd"
BUFFER_SHA = "263eaa17551e807e541937a6e9f9267b9f9836a89f6b15300fff06f332f71782"


def export(scene: Path, source: Path, target: Path):
    scene_bytes, binary = scene.read_bytes(), source.read_bytes()
    if hashlib.sha256(scene_bytes).hexdigest() != SCENE_SHA:
        raise ValueError("Unregistered scene")
    if hashlib.sha256(binary).hexdigest() != BUFFER_SHA:
        raise ValueError("Unregistered geometry buffer")
    part = next(p for p in json.loads(scene_bytes)["parts"] if p["name"] == "thorax")
    if part["triangle_count"] != 18312:
        raise ValueError("Unexpected thorax geometry")
    pos, idx = part["positions"], part["indices"]
    result = (
        binary[pos["byte_offset"] : pos["byte_offset"] + pos["count"] * 4]
        + binary[idx["byte_offset"] : idx["byte_offset"] + idx["count"] * 4]
    )
    target.write_bytes(result)
    print(hashlib.sha256(result).hexdigest(), len(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    export(args.scene, args.binary, args.target)
