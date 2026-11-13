"""Write a reproducible, explicitly independent-cell replay artifact."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

from service.infrastructure.stimulation.synaptic_replay import replay_evidence_json


def export_reference_replay(result, directory: Path):
    """Write new files exclusively and publish the manifest last.

    A missing manifest denotes an incomplete export. Caller owns cleanup of any
    partial files; existing artifacts are never replaced.
    """
    evidence = replay_evidence_json(result)
    time = np.asarray(result["solution"]["time_ms"], dtype=float)
    channel = result["channel"]
    traces = {key: np.asarray(channel[key], dtype=float)
              for key in ("neural_uv", "stimulus_artifact_uv", "total_uv")}
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0) or any(
                value.shape != time.shape or not np.isfinite(value).all()
                for value in traces.values()
            ) or not np.allclose(traces["total_uv"],
                                 traces["neural_uv"] + traces["stimulus_artifact_uv"],
                                 rtol=1e-12, atol=1e-12)):
        raise ValueError("Invalid replay traces")
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = directory / "replay-evidence.json"
    signal_path = directory / "replay-signal.npz"
    manifest_path = directory / "replay-manifest.json"
    # Preflight avoids writing a new partial artifact when a target exists.
    if any(path.exists() for path in (evidence_path, signal_path, manifest_path)):
        raise FileExistsError("Replay artifact already exists")
    with evidence_path.open("xb") as stream:
        stream.write(evidence)
    with signal_path.open("xb") as stream:
        np.savez_compressed(stream, time_ms=time, **traces)
    files = []
    for path in (evidence_path, signal_path):
        raw = path.read_bytes()
        files.append({"name": path.name, "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    manifest = {"format": "independent-swc-replay-artifact-v1", "files": files,
                "units": {"time_ms": "ms", "neural_uv": "µV",
                          "stimulus_artifact_uv": "µV", "total_uv": "µV"},
                "interpretation": "one-way replay; not a coupled or calibrated network"}
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return manifest


def load_verified_reference_replay(directory: Path):
    """Load only complete, hash-checked replay evidence and signal arrays."""
    manifest = json.loads((directory / "replay-manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict)
            or manifest.get("format") != "independent-swc-replay-artifact-v1"
            or not isinstance(manifest.get("files"), list)):
        raise ValueError("Invalid replay manifest")
    files = manifest["files"]
    if (len(files) != 2 or any(not isinstance(item, dict) for item in files)
            or {item.get("name") for item in files} != {
                "replay-evidence.json", "replay-signal.npz"
            }):
        raise ValueError("Invalid replay artifact list")
    checked = {}
    for item in files:
        path = directory / item["name"]
        if (type(item.get("bytes")) is not int or item["bytes"] < 0
                or not isinstance(item.get("sha256"), str)):
            raise ValueError("Invalid replay artifact metadata")
        raw = path.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Replay artifact checksum mismatch")
        checked[item["name"]] = raw
    evidence = json.loads(checked["replay-evidence.json"])
    if (not isinstance(evidence, dict)
            or evidence.get("format") != "independent-swc-replay-evidence-v1"):
        raise ValueError("Invalid replay evidence")
    with np.load(io.BytesIO(checked["replay-signal.npz"]), allow_pickle=False) as loaded:
        names = {"time_ms", "neural_uv", "stimulus_artifact_uv", "total_uv"}
        if set(loaded.files) != names:
            raise ValueError("Invalid replay signal fields")
        traces = {name: np.asarray(loaded[name], dtype=float) for name in names}
    time = traces["time_ms"]
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0) or any(
                value.shape != time.shape or not np.isfinite(value).all()
                for value in traces.values()
            ) or not np.allclose(traces["total_uv"],
                                 traces["neural_uv"] + traces["stimulus_artifact_uv"],
                                 rtol=1e-12, atol=1e-12)):
        raise ValueError("Invalid replay traces")
    return {"manifest": manifest, "evidence": evidence, "traces": traces}
