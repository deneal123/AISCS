"""Validate untrusted executor output before any logical result can be published."""

import re

REQUIRED_FILES = {
    "configuration.json",
    "geometry.json",
    "metrics.json",
    "neural-events.json",
    "preview.json",
    "signal.png",
    "signal.svg",
    "signals.csv",
    "signals.parquet",
    "states.npz",
}


class InvalidManifest(ValueError):
    pass


def validate_manifest(manifest: dict, configuration: dict, digest: str) -> None:
    if not isinstance(manifest, dict) or manifest.get("configuration_sha256") != digest:
        raise InvalidManifest("configuration_integrity")
    if manifest.get("contract_version") != "1.0":
        raise InvalidManifest("contract_version")
    if manifest.get("units") != {"time": "ms", "signal": "uV", "current": "nA", "position": "um"}:
        raise InvalidManifest("physical_units")
    files = manifest.get("files")
    if not isinstance(files, list) or not 10 <= len(files) <= 20:
        raise InvalidManifest("incomplete_artifacts")
    names = set()
    for item in files:
        if not isinstance(item, dict):
            raise InvalidManifest("artifact_identity")
        name, size, checksum = item.get("name"), item.get("bytes"), item.get("sha256")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name)
            or name in {".", "..", "manifest.json"}
            or name in names
        ):
            raise InvalidManifest("artifact_identity")
        if type(size) is not int or not 1 <= size <= 256 * 1024 * 1024:
            raise InvalidManifest("artifact_size")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise InvalidManifest("artifact_hash")
        names.add(name)
    if not REQUIRED_FILES.issubset(names):
        raise InvalidManifest("incomplete_artifacts")
    if configuration.get("model_id") == "male-cns-hybrid-v1":
        if not {
            "connectome.bin",
            "connectome.json",
            "connectome-states.npz",
            "connectome-spikes.parquet",
        }.issubset(names):
            raise InvalidManifest("incomplete_connectome_artifacts")
        graph = manifest.get("connectome", {})
        if (
            not isinstance(graph, dict)
            or graph.get("dataset_id") != "male-cns:v1.0-annotated-nonglial"
            or graph.get("manifest_sha256")
            != "742ee0b22040d6831cb96479d468cd57f1a60d96e2004e3beb421a8d3ac936a2"
            or graph.get("neurons") != 166700
            or graph.get("edges") != 25582938
        ):
            raise InvalidManifest("connectome_identity")
    versions = manifest.get("versions", {})
    if not isinstance(versions, dict) or not all(
        isinstance(versions.get(name), str) and versions[name]
        for name in ("NEURON", "LFPy", "lfpykit", "numpy")
    ):
        raise InvalidManifest("missing_versions")
    metrics = manifest.get("metrics", {})
    expected = round(configuration["duration_ms"] / configuration["dt_ms"]) + 1
    if (
        not isinstance(metrics, dict)
        or type(metrics.get("samples")) is not int
        or metrics["samples"] != expected
    ):
        raise InvalidManifest("time_grid")
