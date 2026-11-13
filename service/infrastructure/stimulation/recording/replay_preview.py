"""Build a loss-aware display preview from a verified replay artifact."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from service.infrastructure.stimulation.recording.replay_export import (
    load_verified_reference_replay,
)


def replay_preview(directory, *, bins=1024):
    """Preserve per-bin extrema in time order; the NPZ remains authoritative."""
    if type(bins) is not int or bins <= 0:
        raise ValueError("Preview bins must be a positive integer")
    source = load_verified_reference_replay(directory)
    traces, evidence = source["traces"], source["evidence"]
    time, signal = traces["time_ms"], traces["neural_uv"]
    if len(time) <= 2 * bins + 2:
        indices = np.arange(len(time))
    else:
        edges = np.linspace(1, len(time) - 1, bins + 1, dtype=int)
        chosen = {0, len(time) - 1}
        for start, end in zip(edges[:-1], edges[1:], strict=True):
            if end <= start:
                continue
            portion = signal[start:end]
            chosen.add(start + int(np.argmin(portion)))
            chosen.add(start + int(np.argmax(portion)))
        indices = np.asarray(sorted(chosen), dtype=int)
    mapping = evidence["mapping"]
    return {"time_ms": time[indices].tolist(), "signal_uv": signal[indices].tolist(),
            "original_samples": len(time), "shown_samples": len(indices),
            "selection": "per-bin minima and maxima in chronological order",
            "signal_scope": "neural contribution of one independently replayed SWC cell",
            "body_id": mapping["body_id"],
            "complete_graph_edge_coverage": mapping.get("complete_graph_edge_coverage", False),
            "limitations": ["Uncalibrated one-way replay; not a full-CNS recording.",
                            "Stimulus artifact is separate and is not shown in this neural trace."],
            "units": {"time_ms": "ms", "signal_uv": "µV"}}


def export_replay_preview(directory):
    """Publish a preview only after validating the complete original export."""
    data = replay_preview(directory)
    payload = (json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
               + "\n").encode("utf-8")
    path = directory / "replay-preview.json"
    with path.open("xb") as stream:
        stream.write(payload)
    return {"name": path.name, "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}
