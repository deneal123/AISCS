"""Summarise local threshold crossings without treating them as cell spikes."""

from __future__ import annotations

import math

import numpy as np


def compartment_crossing_summary(time_ms, voltage_mv, *, selected_index, threshold_mv):
    """Report sampled upward crossings, including compartments not sent to the graph.

    First-crossing times are sample times, not inferred continuous spike times.
    Initial samples at or above the threshold are reported separately because
    their earlier history is unknown. Full traces are not stored by this summary.
    """
    time = np.asarray(time_ms, dtype=float)
    voltage = np.asarray(voltage_mv, dtype=float)
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0) or voltage.ndim != 2
            or voltage.shape[0] < 1 or voltage.shape[1] != len(time)
            or not np.isfinite(voltage).all() or type(selected_index) is not int
            or not 0 <= selected_index < len(voltage)
            or isinstance(threshold_mv, bool | np.bool_)
            or not isinstance(threshold_mv, int | float) or not math.isfinite(threshold_mv)):
        raise ValueError("Invalid compartment crossing inputs")
    total_crossing = 0
    first_index = None
    selected_count = 0
    selected_first = None
    for start in range(0, len(voltage), 256):
        chunk = voltage[start:start + 256]
        crossings = (chunk[:, :-1] < threshold_mv) & (chunk[:, 1:] >= threshold_mv)
        crossing_rows = np.any(crossings, axis=1)
        if np.any(crossing_rows):
            total_crossing += int(np.count_nonzero(crossing_rows))
            current = int(np.argmax(np.any(crossings, axis=0))) + 1
            first_index = current if first_index is None else min(first_index, current)
            if start <= selected_index < start + len(chunk):
                selected_crossings = crossings[selected_index - start]
                selected_count = int(np.count_nonzero(selected_crossings))
                if selected_count:
                    selected_first = float(time[int(np.argmax(selected_crossings)) + 1])
    return {
        "compartments": len(voltage),
        "initial_at_or_above_threshold": int(np.count_nonzero(voltage[:, 0] >= threshold_mv)),
        "compartments_with_upward_crossing": total_crossing,
        "earliest_crossing_sample_ms": None if first_index is None else float(time[first_index]),
        "selected_crossings": selected_count,
        "selected_first_crossing_sample_ms": selected_first,
    }


def compartment_crossing_events(time_ms, voltage_mv, midpoints_um, *, threshold_mv,
                                max_events=1_000_000):
    """Return bounded sampled threshold transitions with their actual model locations.

    This is not a reconstructed axonal wave or a detected physiological spike.
    Coordinates are solver compartment midpoints in the native model frame;
    each event time is the first sample at or above the threshold. Initial
    supra-threshold values are not represented as transitions.
    """
    time = np.asarray(time_ms, dtype=float)
    voltage = np.asarray(voltage_mv, dtype=float)
    positions = np.asarray(midpoints_um, dtype=float)
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or np.any(np.diff(time) <= 0) or voltage.ndim != 2
            or voltage.shape[0] < 1 or voltage.shape[1] != len(time)
            or not np.isfinite(voltage).all() or positions.shape != (len(voltage), 3)
            or not np.isfinite(positions).all() or isinstance(threshold_mv, bool | np.bool_)
            or not isinstance(threshold_mv, int | float) or not math.isfinite(threshold_mv)
            or type(max_events) is not int or max_events < 1):
        raise ValueError("Invalid compartment crossing event inputs")
    segments, samples, count = [], [], 0
    for start in range(0, len(voltage), 256):
        chunk = voltage[start:start + 256]
        crossings = (chunk[:, :-1] < threshold_mv) & (chunk[:, 1:] >= threshold_mv)
        count += int(np.count_nonzero(crossings))
        if count > max_events:
            raise ValueError("Compartment crossing event limit exceeded")
        rows, columns = np.nonzero(crossings)
        if len(rows):
            segments.append(rows.astype(np.int64) + start)
            samples.append(columns.astype(np.int64) + 1)
    if not segments:
        return {"compartment_indices": np.empty(0, dtype=np.int64),
                "sample_indices": np.empty(0, dtype=np.int64),
                "midpoints_um": positions.copy()}
    return {"compartment_indices": np.concatenate(segments),
            "sample_indices": np.concatenate(samples),
            "midpoints_um": positions.copy()}
