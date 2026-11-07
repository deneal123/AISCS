"""Read an explicitly published, checksum-verified CNS overview generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from service.infrastructure.connectome.dataset import MANIFEST_SHA256


def overview_manifest(directory: Path) -> dict:
    document = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("manifest_sha256") != MANIFEST_SHA256
        or document.get("dataset_id") != "male-cns:v1.0-annotated-nonglial"
        or document.get("method") != "evenly-sampled-original-swc-edges-v1"
        or document.get("source_frame") != "MaleCNS native unmirrored EM"
        or document.get("units") != "um"
        or document.get("record_bytes") != 28
        or type(document.get("edges_per_neuron_max")) is not int
        or not 1 <= document["edges_per_neuron_max"] <= 32
        or not isinstance(document.get("chunks"), list)
    ):
        raise ValueError("Invalid overview identity")
    end = 0
    for item in document["chunks"]:
        if (
            not isinstance(item, dict)
            or item.get("start") != end
            or item.get("file") != f"overview-{end:06d}.bin.gz"
            or type(item.get("cells")) is not int
            or not 0 < item["cells"] <= 10000
            or type(item.get("cells_with_edges")) is not int
            or not 0 <= item["cells_with_edges"] <= item["cells"]
            or type(item.get("bytes")) is not int
            or not 0 < item["bytes"] <= 16_000_000
            or not isinstance(item.get("sha256"), str)
            or len(item["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in item["sha256"])
        ):
            raise ValueError("Invalid overview chunk")
        end += item["cells"]
    if end != 166700:
        raise ValueError("Incomplete overview coverage")
    return document


def overview_chunk(directory: Path, name: str) -> bytes:
    manifest = overview_manifest(directory)
    record = next((item for item in manifest["chunks"] if item["file"] == name), None)
    if record is None:
        raise FileNotFoundError("Overview chunk not registered")
    path = directory / name
    if path.stat().st_size != record["bytes"]:
        raise ValueError("Overview chunk size mismatch")
    binary = path.read_bytes()
    if hashlib.sha256(binary).hexdigest() != record["sha256"]:
        raise ValueError("Overview chunk checksum mismatch")
    return binary
