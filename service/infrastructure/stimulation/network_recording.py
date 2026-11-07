"""Streaming superposition of independently computed compartmental recordings.

This operator does not create neural currents, couple cells, or validate the
mapping between the specimen and the visible body.
"""

from __future__ import annotations

import hashlib
import json
import re

import numpy as np

from service.infrastructure.stimulation.acquisition import acquire_channel
from service.infrastructure.stimulation.swc_reference import record_swc_with_stimulus_artifact


def record_independent_cells(
    records, electrode_um, reference_um, *, source_model="pointsource", provenance_sink=None,
):
    """Sum checked cell currents on one time grid and add the common artifact once.

    Records are (solution, provenance) pairs, consumed incrementally. Solutions
    must use a common stimulation, medium and native coordinate frame. This is
    not a network simulation: it only combines supplied membrane currents.
    If supplied, provenance_sink receives canonical UTF-8 JSONL in cell order;
    the caller owns its lifetime and must retain it for reproducibility.
    """
    seen = set()
    identity = hashlib.sha256()
    provenance_identity = hashlib.sha256()
    provenance_complete = True
    time = stimulus = waveform = neural = parameters = None
    for solution, provenance in records:
        body_id = provenance.get("body_id")
        source_sha = provenance.get("morphology_sha256")
        if (not isinstance(body_id, str) or not re.fullmatch(r"[1-9]\d*", body_id)
                or body_id in seen or not isinstance(source_sha, str)
                or not re.fullmatch(r"[0-9a-f]{64}", source_sha)
                or provenance.get("coordinate_frame") != "MaleCNS native EM, micrometres"):
            raise ValueError("Invalid or duplicate cell provenance")
        required = ("neuron_version", "numpy_version", "membrane_model", "fixed_parameters",
                    "fragment_interpretation", "configuration")
        config_fields = ("dt_ms", "duration_ms", "nseg_per_edge", "axial_resistivity_ohm_cm",
                         "membrane_capacitance_uf_cm2", "temperature_c", "initial_voltage_mv",
                         "allow_disconnected")
        config = provenance.get("configuration")
        provenance_complete &= (
            all(key in provenance and provenance[key] is not None for key in required)
            and isinstance(config, dict) and all(key in config for key in config_fields)
        )
        try:
            provenance_line = (json.dumps(
                provenance, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False,
            ) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Cell provenance must be finite JSON") from exc
        cell_time = np.asarray(solution["time_ms"], dtype=float)
        if (cell_time.ndim != 1 or len(cell_time) < 2 or not np.isfinite(cell_time).all()
                or np.any(np.diff(cell_time) <= 0)):
            raise ValueError("Invalid recording time grid")
        channel = record_swc_with_stimulus_artifact(
            solution, provenance, electrode_um, reference_um, source_model=source_model
        )
        if time is None:
            time = cell_time.copy()
            stimulus = channel["stimulus_artifact_uv"].copy()
            waveform = np.asarray(solution["stimulus_fraction"], dtype=float).copy()
            parameters = np.asarray(solution["stimulation_parameters"]).copy()
            neural = np.zeros_like(time)
        elif (not np.array_equal(time, cell_time)
              or not np.array_equal(parameters, solution["stimulation_parameters"])
              or not np.array_equal(waveform, solution["stimulus_fraction"])
              or not np.array_equal(stimulus, channel["stimulus_artifact_uv"])):
            raise ValueError("Cells do not share the time grid and stimulation artifact")
        neural += channel["neural_uv"]
        if not np.isfinite(neural).all():
            raise ValueError("Non-finite aggregate recording")
        seen.add(body_id)
        identity.update(f"{body_id}:{source_sha}\n".encode("ascii"))
        provenance_identity.update(provenance_line)
        if provenance_sink is not None:
            if provenance_sink.write(provenance_line) != len(provenance_line):
                raise OSError("Incomplete cell provenance write")
    if time is None:
        raise ValueError("No cell recordings")
    with np.errstate(over="ignore", invalid="ignore"):
        total = neural + stimulus
    if not np.isfinite(total).all():
        raise ValueError("Non-finite aggregate recording")
    return {"time_ms": time, "neural_uv": neural, "stimulus_artifact_uv": stimulus,
            "stimulus_fraction": waveform, "total_uv": total, "cells": len(seen),
            "ordered_sources_sha256": identity.hexdigest(), "source_model": source_model,
            "cell_provenance_sha256": provenance_identity.hexdigest(),
            "cell_provenance_exported": provenance_sink is not None,
            "cell_provenance_fields_present": provenance_complete,
            "stimulation_parameters": {
                "source_um": parameters[:3].tolist(), "return_um": parameters[3:6].tolist(),
                "current_na": float(parameters[6]), "conductivity_s_m": float(parameters[7]),
                "clearance_um": float(parameters[8]), "pulse_start_ms": float(parameters[9]),
                "pulse_end_ms": float(parameters[10]), "rise_time_ms": float(parameters[11]),
                "interphase_gap_ms": float(parameters[12]),
                "pulse_shape": "biphasic" if parameters[13] == 1 else "monophasic",
                **({"pulse_count": int(parameters[14]), "pulse_interval_ms": float(parameters[15])}
                   if len(parameters) == 16 else {}),
            },
            "electrode_um": np.asarray(electrode_um, dtype=float).tolist(),
            "reference_um": np.asarray(reference_um, dtype=float).tolist(),
            "coordinate_frame": "MaleCNS native EM, micrometres"}


def acquire_independent_cells(recording, *, low_hz, high_hz, recovery_ms=0, clip_uv=None):
    """Apply the engineering acquisition model to an independent-cell sum.

    The input is not evidence of coupled network dynamics or anatomical registration.
    """
    acquired = acquire_channel(
        recording["time_ms"], recording["neural_uv"], recording["stimulus_artifact_uv"],
        recording["stimulus_fraction"], low_hz=low_hz, high_hz=high_hz,
        recovery_ms=recovery_ms, clip_uv=clip_uv,
    )
    acquired["recording_provenance"] = {
        "cells": recording["cells"], "ordered_sources_sha256": recording["ordered_sources_sha256"],
        "cell_provenance_sha256": recording["cell_provenance_sha256"],
        "cell_provenance_exported": recording["cell_provenance_exported"],
        "cell_provenance_fields_present": recording["cell_provenance_fields_present"],
        "source_model": recording["source_model"], "coupling": "independent cells",
        "stimulation_parameters": recording["stimulation_parameters"],
        "electrode_um": recording["electrode_um"], "reference_um": recording["reference_um"],
        "coordinate_frame": recording["coordinate_frame"],
    }
    return acquired
