"""Serve the published view-only MaleCNS neuropil surface generation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from service.infrastructure.connectome.dataset import MANIFEST_SHA256

DATASETS = {"fullbrain-roi-v4": 90, "malecns-vnc-neuropil-roi-v0": 24}


def neuropil_manifest(directory: Path):
    document = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(document, dict) or document.get("manifest_sha256") != MANIFEST_SHA256
            or document.get("dataset_id") != "male-cns:v1.0-annotated-nonglial"
            or document.get("source_frame") != "MaleCNS native unmirrored EM"
            or document.get("units") != "um"
            or document.get("method") != "vertex-grid-visual-lod-v1"
            or type(document.get("grid_um")) not in (int, float)
            or not math.isfinite(document["grid_um"]) or not 0 < document["grid_um"] <= 10
            or not isinstance(document.get("meshes"), list)):
        raise ValueError("Invalid neuropil generation")
    seen, counts = set(), {dataset: 0 for dataset in DATASETS}
    for record in document["meshes"]:
        if not isinstance(record, dict):
            raise ValueError("Invalid neuropil mesh")
        dataset, segment = record.get("dataset"), record.get("id")
        if (dataset not in DATASETS or not isinstance(segment, str)
                or not re.fullmatch(r"[1-9]\d*", segment) or (dataset, segment) in seen
                or record.get("file") != f"{dataset}-{segment}.bin.gz"
                or not isinstance(record.get("label"), str) or not 0 < len(record["label"]) <= 100
                or any(not isinstance(record.get(key), str)
                       or not re.fullmatch(r"[0-9a-f]{64}", record[key])
                       for key in ("sha256", "source_sha256"))
                or any(type(record.get(key)) is not int or not 0 < record[key] <= 16_000_000
                       for key in ("bytes", "vertices", "triangles"))
                or type(record.get("max_vertex_displacement_um")) not in (int, float)
                or not math.isfinite(record["max_vertex_displacement_um"])
                or not 0 <= record["max_vertex_displacement_um"]
                <= math.sqrt(3) * document["grid_um"] + 1e-9):
            raise ValueError("Invalid neuropil mesh")
        seen.add((dataset, segment))
        counts[dataset] += 1
    if counts != DATASETS:
        raise ValueError("Incomplete neuropil generation")
    return document


def neuropil_chunk(directory: Path, name: str):
    manifest = neuropil_manifest(directory)
    record = next((mesh for mesh in manifest["meshes"] if mesh["file"] == name), None)
    if record is None:
        raise FileNotFoundError("Neuropil mesh not registered")
    binary = (directory / name).read_bytes()
    if len(binary) != record["bytes"] or hashlib.sha256(binary).hexdigest() != record["sha256"]:
        raise ValueError("Neuropil mesh checksum mismatch")
    return binary
