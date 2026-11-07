"""Select a reproducible source trace from a solved, stimulated morphology.

An earliest sampled threshold crossing is an engineering selection rule, not a
physiological spike detector or a claim about a synaptic output location. It
also does not establish that the stimulus caused the crossing; a matching
unstimulated control is required before making a causal interpretation.
"""

from __future__ import annotations

import math

import numpy as np

from service.infrastructure.connectome.forced_network import threshold_crossing_ticks


def earliest_crossing_source(time_ms, voltage_mv, edge_node_ids, *, threshold_mv, duration_ms):
    """Return the earliest crossing compartment and its complete checked trace.

    Ties are resolved by the original solver segment order. Initially
    suprathreshold cells fail closed because their crossing history is unknown.
    A missing crossing returns None. Integer network ticks are checked by the
    same routine used by the graph; ambiguous tick boundaries are rejected.
    """
    time = np.asarray(time_ms, dtype=np.float64)
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    edges = np.asarray(edge_node_ids)
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or time[0] != 0 or np.any(np.diff(time) <= 0)
            or voltage.ndim != 2 or voltage.shape[0] < 1 or voltage.shape[1] != len(time)
            or not np.isfinite(voltage).all() or edges.shape != (voltage.shape[0],)
            or edges.dtype.kind not in 'iu' or np.any(edges <= 0)
            or isinstance(threshold_mv, bool | np.bool_)
            or not isinstance(threshold_mv, int | float) or not math.isfinite(threshold_mv)
            or type(duration_ms) is not int or duration_ms < 1
            or time[-1] < duration_ms - 1e-9):
        raise ValueError('Invalid source selection inputs')
    if np.any(voltage[:, 0] >= threshold_mv):
        raise ValueError('Initially suprathreshold compartments have unknown history')
    first_sample = None
    first_segment = None
    chunk_size = max(1, min(256, 2_000_000 // max(len(time) - 1, 1)))
    for start in range(0, len(voltage), chunk_size):
        chunk = voltage[start:start + chunk_size]
        crossing = (chunk[:, :-1] < threshold_mv) & (chunk[:, 1:] >= threshold_mv)
        by_sample = np.any(crossing, axis=0)
        if np.any(by_sample):
            earliest = int(np.argmax(by_sample)) + 1
            segment = int(np.argmax(crossing[:, earliest - 1])) + start
            if first_sample is None or (earliest, segment) < (first_sample, first_segment):
                first_sample, first_segment = earliest, segment
    if first_sample is None:
        return None
    edge_id = int(edges[first_segment])
    segments = np.flatnonzero(edges == edge_id)
    if not np.array_equal(segments, np.arange(segments[0], segments[0] + len(segments))):
        raise ValueError('Source edge segments are not contiguous')
    nseg = len(segments)
    if nseg % 2 == 0:
        raise ValueError('Source edge must have an odd number of segments')
    index_within_edge = first_segment - int(segments[0])
    ticks = threshold_crossing_ticks(time, voltage[first_segment], threshold_mv=threshold_mv,
                                     duration_ms=duration_ms)
    return {'child_node_id': edge_id, 'sampling_fraction': (index_within_edge + .5) / nseg,
            'segment_index': first_segment, 'first_sample_ms': float(time[first_sample]),
            'event_ticks_ms': ticks.tolist(),
            'interpretation': 'earliest sampled threshold crossing; not a validated spike'}
