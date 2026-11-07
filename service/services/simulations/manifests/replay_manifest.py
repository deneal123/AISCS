"""Validate isolated replay output before accepting it into owned storage."""

from __future__ import annotations

import math
import re
from uuid import UUID


class InvalidReplayManifest(ValueError):
    pass


def validate_replay_manifest(manifest, *, configuration_sha256: str, source_run_id: UUID):
    if (not isinstance(manifest, dict)
            or manifest.get("format") != "independent-swc-replay-artifact-v1"
            or manifest.get("kind") != "independent-cell-replay"
            or not isinstance(configuration_sha256, str) or not isinstance(source_run_id, UUID)
            or manifest.get("configuration_sha256") != configuration_sha256
            or not re.fullmatch(r"[a-f0-9]{64}", configuration_sha256)
            or manifest.get("source_run_id") != str(source_run_id)):
        raise InvalidReplayManifest("replay_identity")
    if manifest.get("units") != {"time_ms": "ms", "neural_uv": "µV",
                                 "stimulus_artifact_uv": "µV", "total_uv": "µV"}:
        raise InvalidReplayManifest("replay_units")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 3:
        raise InvalidReplayManifest("replay_files")
    names = set()
    for item in files:
        if not isinstance(item, dict):
            raise InvalidReplayManifest("replay_files")
        name, size, checksum = item.get("name"), item.get("bytes"), item.get("sha256")
        if (name not in {"replay-evidence.json", "replay-signal.npz", "replay-preview.json"}
                or name in names
                or type(size) is not int or not 1 <= size <= 256 * 1024 * 1024
                or (name == "replay-preview.json" and size > 1024 * 1024)
                or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum)):
            raise InvalidReplayManifest("replay_files")
        names.add(name)
    if names != {"replay-evidence.json", "replay-signal.npz", "replay-preview.json"}:
        raise InvalidReplayManifest("replay_files")


def validate_replay_preview(preview, configuration):
    """Reject malformed or misidentified traces before placing them in a run result."""
    if not isinstance(preview, dict) or not isinstance(configuration, dict):
        raise InvalidReplayManifest("replay_preview")
    try:
        simulation = configuration["simulation"]
        duration, dt = simulation["duration_ms"], simulation["dt_ms"]
        body_id = configuration["body_id"]
        times, signal = preview["time_ms"], preview["signal_uv"]
        original, shown = preview["original_samples"], preview["shown_samples"]
        if (type(body_id) is not int or type(duration) not in (int, float)
                or type(dt) not in (int, float) or not math.isfinite(duration)
                or not math.isfinite(dt) or duration <= 0 or dt <= 0
                or not isinstance(times, list) or not isinstance(signal, list)
                or type(original) is not int or type(shown) is not int
                or original != round(duration / dt) + 1 or shown != len(times)
                or not 2 <= shown <= min(original, 2050) or len(signal) != shown
                or preview["body_id"] != str(body_id)
                or preview["units"] != {"time_ms": "ms", "signal_uv": "µV"}
                or preview["signal_scope"] !=
                "neural contribution of one independently replayed SWC cell"
                or type(preview["complete_graph_edge_coverage"]) is not bool
                or not isinstance(preview["limitations"], list)
                or not all(isinstance(value, str) for value in preview["limitations"])
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in times + signal)
                or not math.isclose(times[0], 0, rel_tol=0, abs_tol=1e-8)
                or not math.isclose(times[-1], duration, rel_tol=0, abs_tol=1e-8)
                or any(a >= b for a, b in zip(times, times[1:], strict=False))):
            raise InvalidReplayManifest("replay_preview")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise InvalidReplayManifest("replay_preview") from exc
