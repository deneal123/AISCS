"""Verified, bounded preview of a new E1/REF recording from retained currents."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from service.infrastructure.stimulation.network_recording import acquire_independent_cells
from service.infrastructure.stimulation.recording.current_archive import rerecord_current_archive
from service.infrastructure.stimulation.recording.current_transport import unpack_current_archive


def rerecord_preview(
    package: Path, package_sha256: str, manifest_sha256: str, workspace: Path,
    electrode_um, reference_um, *, source_model="pointsource", acquisition=None, bins=256,
):
    """Do not change the original archive or claim a new neural simulation occurred."""
    if type(bins) is not int or not 1 <= bins <= 341:
        raise ValueError("Invalid preview bin count")
    workspace.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="rerecord-", dir=workspace) as temporary:
        directory = Path(temporary) / "currents"
        unpack_current_archive(package, package_sha256, manifest_sha256, directory)
        result = rerecord_current_archive(
            directory, manifest_sha256, electrode_um, reference_um, source_model=source_model
        )
        acquired = acquire_independent_cells(result, **acquisition) if acquisition else None
        time = result["time_ms"]
        names = ["neural_uv", "stimulus_artifact_uv", "total_uv", "stimulus_fraction"]
        signals = [result[name] for name in names]
        if acquired is not None:
            signals.append(acquired["filtered_total_uv"])
        edges = np.linspace(0, len(time), min(bins, len(time)) + 1, dtype=int)
        selected, validity, saturated, intervals = set(), {}, {}, []
        for start, end in zip(edges[:-1], edges[1:], strict=True):
            candidates = {start, end - 1}
            for signal in signals:
                candidates.update((start + int(np.argmin(signal[start:end])),
                                   start + int(np.argmax(signal[start:end]))))
            if acquired is not None:
                interval = {
                    "start_ms": float(time[0] if start == 0 else
                                      (time[start - 1] + time[start]) / 2),
                    "end_ms": float(time[-1] if end == len(time) else
                                    (time[end - 1] + time[end]) / 2),
                    "valid": bool(np.all(acquired["valid_samples"][start:end])),
                    "saturated": bool(np.any(acquired["saturated_samples"][start:end])),
                }
                if (intervals and intervals[-1]["valid"] == interval["valid"]
                        and intervals[-1]["saturated"] == interval["saturated"]):
                    intervals[-1]["end_ms"] = interval["end_ms"]
                else:
                    intervals.append(interval)
            for index in candidates:
                selected.add(index)
                if acquired is not None:
                    validity[index] = bool(np.all(acquired["valid_samples"][start:end]))
                    saturated[index] = bool(np.any(acquired["saturated_samples"][start:end]))
        indices = np.asarray(sorted(selected), dtype=int)
        response = {
            "time_ms": time[indices].tolist(),
            **{name: result[name][indices].tolist() for name in names},
            "samples": len(time), "shown_samples": len(indices), "cells": result["cells"],
            "electrode_um": result["electrode_um"], "reference_um": result["reference_um"],
            "source_model": result["source_model"], "coordinate_frame": result["coordinate_frame"],
            "package_sha256": package_sha256, "current_manifest_sha256": manifest_sha256,
            "selection": "per-bin endpoints and signal extrema",
            "interpretation": result["interpretation"],
        }
        if acquired is not None:
            response["acquisition"] = {
                "filtered_total_uv": acquired["filtered_total_uv"][indices].tolist(),
                "valid_samples": [validity[int(index)] for index in indices],
                "saturated_samples": [saturated[int(index)] for index in indices],
                "mask_scope": "conservative aggregation over the source bin",
                "mask_intervals": intervals,
                "settings": acquired["settings"],
            }
        return response
