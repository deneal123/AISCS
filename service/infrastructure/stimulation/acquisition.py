"""Explicit engineering acquisition model for simulated extracellular signals."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import butter, sosfilt


def acquire_channel(time_ms, neural_uv, artifact_uv, stimulus_fraction, *, low_hz, high_hz,
                    recovery_ms=0.0, clip_uv=None):
    """Apply a causal bandpass and mark samples blanked during the single pulse.

    The filter starts at zero state. Optional symmetric clipping is an ideal
    memoryless front-end, not electrode polarization or a calibrated amplifier.
    Blanking hides samples but filtering continues through the complete signal.
    If clipping occurs, all samples from the first clipped sample onward are
    marked invalid: the filter has memory and no recovery model is provided.
    """
    time = np.asarray(time_ms, dtype=float)
    neural = np.asarray(neural_uv, dtype=float)
    artifact = np.asarray(artifact_uv, dtype=float)
    stimulus = np.asarray(stimulus_fraction, dtype=float)
    if (time.ndim != 1 or len(time) < 3 or neural.shape != time.shape
            or artifact.shape != time.shape or stimulus.shape != time.shape
            or not all(np.isfinite(array).all() for array in (time, neural, artifact, stimulus))):
        raise ValueError("Invalid acquisition data")
    differences = np.diff(time)
    dt = float(differences[0])
    if dt <= 0 or not np.allclose(differences, dt, rtol=1e-8, atol=1e-10):
        raise ValueError("Acquisition requires a uniform increasing time grid")
    scalars = (low_hz, high_hz, recovery_ms)
    if (any(isinstance(value, bool | np.bool_) or not math.isfinite(value) for value in scalars)
            or recovery_ms < 0 or not 0 < low_hz < high_hz < 500 / dt):
        raise ValueError("Invalid acquisition bandwidth or recovery")
    if clip_uv is not None and (isinstance(clip_uv, bool | np.bool_)
                                or not math.isfinite(clip_uv) or clip_uv <= 0):
        raise ValueError("Invalid acquisition clipping threshold")
    sampling_hz = 1000 / dt
    sos = butter(2, [low_hz, high_hz], btype="bandpass", fs=sampling_hz, output="sos")
    with np.errstate(over="ignore", invalid="ignore"):
        raw = neural + artifact
    if not np.isfinite(raw).all():
        raise ValueError("Acquisition signal sum is not finite")
    saturated = np.abs(raw) > clip_uv if clip_uv is not None else np.zeros(len(time), dtype=bool)
    amplifier_input = np.clip(raw, -clip_uv, clip_uv) if clip_uv is not None else raw
    filtered = sosfilt(sos, amplifier_input)
    if not np.isfinite(filtered).all():
        raise ValueError("Acquisition filter output is not finite")
    active = np.flatnonzero(np.abs(stimulus) > 1e-9)
    valid = np.ones(len(time), dtype=bool)
    if len(active):
        end = np.searchsorted(time, time[active[-1]] + recovery_ms, side="right")
        valid[active[0]:end] = False
    if saturated.any():
        valid[np.flatnonzero(saturated)[0]:] = False
    result = {"time_ms": time.copy(), "raw_total_uv": raw, "filtered_total_uv": filtered,
              "valid_samples": valid, "saturated_samples": saturated,
              "settings": {"low_hz": float(low_hz), "high_hz": float(high_hz),
                           "sampling_hz": sampling_hz, "filter": "causal Butterworth order 2",
                           "recovery_ms": float(recovery_ms), "clip_uv": clip_uv,
                           "blanking": "first to last active pulse sample plus recovery",
                           "saturation_validity": "invalid from first clipping to end"}}
    if clip_uv is None:
        result["filtered_neural_uv"] = sosfilt(sos, neural)
        result["filtered_artifact_uv"] = sosfilt(sos, artifact)
        if not (np.isfinite(result["filtered_neural_uv"]).all()
                and np.isfinite(result["filtered_artifact_uv"]).all()):
            raise ValueError("Acquisition component output is not finite")
    return result
