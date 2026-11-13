"""Validate and order one-segment events for the experimental GPU prototype.

Only one-segment SWC edges and interior locations are supported. NEURON places
interior point processes on the containing finite segment; exact endpoints
are different and require explicitly audited relocation or a different solver.
"""

from math import isfinite


def midpoint_events(events, edge_child_ids, *, duration_ms, nseg_per_edge):
    """Return chronological interior events with one-segment indexes."""
    if (not isinstance(events, list) or not isinstance(edge_child_ids, list)
            or any(type(node) is not int or node <= 0 for node in edge_child_ids)
            or len(set(edge_child_ids)) != len(edge_child_ids)
            or isinstance(duration_ms, bool) or not isinstance(duration_ms, int | float)
            or not isfinite(duration_ms) or duration_ms <= 0
            or type(nseg_per_edge) is not int or nseg_per_edge != 1):
        raise ValueError('Invalid event mapping inputs')
    indexes = {node: i for i, node in enumerate(edge_child_ids)}
    ordered = []
    keys = {'child_node_id', 'position', 'time_ms', 'weight_us', 'tau1_ms',
            'tau2_ms', 'reversal_mv'}
    for event in events:
        if not isinstance(event, dict) or set(event) != keys:
            raise ValueError('Invalid event fields')
        child = event['child_node_id']
        if type(child) is not int or child not in indexes:
            raise ValueError('Event references an unknown SWC edge')
        for key in keys - {'child_node_id'}:
            value = event[key]
            if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
                raise ValueError('Invalid event parameter')
        if (not 0 < event['position'] < 1 or not 0 < event['time_ms'] < duration_ms
                or event['weight_us'] <= 0 or not 0 < event['tau1_ms'] < event['tau2_ms']
                or not 1e-9 <= event['tau1_ms'] / event['tau2_ms'] <= .9999):
            raise ValueError('Unsupported event position, timing or kinetics')
        ordered.append({**event, 'segment_index': indexes[child]})
    return sorted(ordered, key=lambda item: item['time_ms'])


def _verified_feedback_events(schedule, body_id, morphology_sha256):
    if (not isinstance(schedule, dict) or type(body_id) is not int or body_id <= 0
            or not isinstance(morphology_sha256, str) or len(morphology_sha256) != 64
            or any(c not in '0123456789abcdef' for c in morphology_sha256)
            or schedule.get('unresolved') != []
            or not isinstance(schedule.get('events_by_target'), dict)
            or not isinstance(schedule.get('target_morphology_sha256'), dict)
            or schedule['target_morphology_sha256'].get(body_id) != morphology_sha256
            or body_id not in schedule['events_by_target']):
        raise ValueError('Incomplete feedback schedule or morphology mismatch')
    return schedule['events_by_target'][body_id]


def feedback_midpoint_events(schedule, body_id, morphology_sha256, edge_child_ids, *,
                             duration_ms, nseg_per_edge):
    """Map a complete feedback schedule only to its verified target morphology."""
    events = _verified_feedback_events(schedule, body_id, morphology_sha256)
    return midpoint_events(events, edge_child_ids, duration_ms=duration_ms,
                           nseg_per_edge=nseg_per_edge)


def refined_segment_events(events, segments, *, duration_ms):
    """Map interior events onto an explicitly ordered odd-resolution grid.

    ``segments`` contains ``(SWC child ID, zero-based index, edge nseg)`` in
    solver-array order. Exact endpoints remain unsupported; callers must first
    apply and verify the separate endpoint-discretization policy.
    """
    if not isinstance(segments, list):
        raise ValueError('Invalid refined segment grid')
    indexes = {}
    counts = {}
    seen_per_child = {}
    for index, entry in enumerate(segments):
        if (not isinstance(entry, tuple) or len(entry) != 3
                or any(type(value) is not int for value in entry)):
            raise ValueError('Invalid refined segment grid')
        child, segment, count = entry
        if (child <= 0 or count < 1 or count % 2 != 1 or not 0 <= segment < count
                or (child, segment) in indexes or child in counts and counts[child] != count):
            raise ValueError('Invalid refined segment grid')
        indexes[child, segment] = index
        counts[child] = count
        seen_per_child[child] = seen_per_child.get(child, 0) + 1
    # Bounds and duplicate checks above ensure that exactly ``count`` unique
    # indices necessarily cover every segment, regardless of input ordering.
    if any(seen_per_child[child] != count for child, count in counts.items()):
        raise ValueError('Incomplete refined segment grid')
    # Reuse strict field, numeric and endpoint checks; the temporary mapping
    # only validates events and does not choose their final segment.
    checked = midpoint_events(events, list(counts), duration_ms=duration_ms, nseg_per_edge=1)
    for row in checked:
        child = row['child_node_id']
        segment = min(int(row['position'] * counts[child]), counts[child] - 1)
        row['segment_index'] = indexes[child, segment]
    return checked


def feedback_refined_events(schedule, body_id, morphology_sha256, segments, *, duration_ms):
    """Map verified feedback onto an explicitly ordered refined segment grid."""
    events = _verified_feedback_events(schedule, body_id, morphology_sha256)
    return refined_segment_events(events, segments, duration_ms=duration_ms)
