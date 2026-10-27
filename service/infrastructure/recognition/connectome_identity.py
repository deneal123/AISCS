"""Bind a frozen classifier to numerical sources, data and installed runtime."""

import hashlib
import importlib.metadata
import json
from pathlib import Path

from service.infrastructure.connectome.dataset import MANIFEST_SHA256


def numerical_identity() -> dict:
    root = Path(__file__).resolve().parents[1]
    paths = [
        "connectome/dataset.py",
        "connectome/network.py",
        "connectome/kernel.py",
        "connectome/solver.py",
        "neuron/solver.py",
        "lfpy/recording.py",
    ]
    sources = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
    for name in ["geometry.py", "connectome_signals.py", "recording_noise.py"]:
        sources["domain/" + name] = hashlib.sha256(
            (root.parent / "domain" / name).read_bytes()
        ).hexdigest()
    versions = {
        name: importlib.metadata.version(name)
        for name in ("NEURON", "LFPy", "lfpykit", "numpy", "numba", "llvmlite")
    }
    payload = {
        "preset": "male-cns-hybrid-v1",
        "graph_manifest_sha256": MANIFEST_SHA256,
        "sources": sources,
        "versions": versions,
    }
    return {
        **payload,
        "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
    }
