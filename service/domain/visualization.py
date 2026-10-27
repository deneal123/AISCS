"""Recorded visualization semantics; no stimulus labels drive the body response."""

import numpy as np

VISUALIZATION = {
    "version": "compartment-events-and-leg-preview-v1",
    "event_threshold_mv": -10.0,
    "highlight_ms": 5.0,
    "input": {
        "kind": "scheduled-ExpSyn-events-v1",
        "event_weight_unit": "uS",
        "max_event_weight_us": 0.009,
        "highlight_ms": 2.0,
        "description": "Scheduled synaptic conductance increments, not an external field",
    },
    "reaction": {
        "kind": "phenomenological-coxa-rotation-v1",
        "decay_ms": 8.0,
        "window_ms": 24.0,
        "normalization": 3.0,
        "max_angle_rad": 0.25,
        "input": "calculated soma spike events",
        "validated_biomechanics": False,
    },
}


def compartment_events(time_ms, voltage_mv) -> list[dict]:
    result = []
    threshold = VISUALIZATION["event_threshold_mv"]
    for segment, voltage in enumerate(voltage_mv):
        crossings = np.flatnonzero((voltage[:-1] < threshold) & (voltage[1:] >= threshold)) + 1
        result.extend(
            {"segment_id": segment, "time_ms": float(time_ms[index])} for index in crossings
        )
    return result
