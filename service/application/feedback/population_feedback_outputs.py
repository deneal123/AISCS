"""Re-evaluate registered source-output crossings after a feedback replay."""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from service.infrastructure.connectome.forced_network import threshold_crossing_ticks


def feedback_output_events(body, solution, provenance, original, *, threshold_mv, duration_ms,
                           include_candidates=False, max_source_distance_um=None):
    """Extract model edge events at previously verified outgoing compartments.

    Original geometry must already have passed fragment archive verification.
    This function does not infer that fragmented morphology is connected.
    """
    if (type(body) is not int or body <= 0 or not isinstance(original, dict)
            or original.get('body_id') != str(body) or provenance.get('body_id') != str(body)
            or provenance.get('morphology_sha256') != original.get('morphology_sha256')
            or original.get('threshold_mv') != threshold_mv
            or original.get('duration_ms') != duration_ms
            or not isinstance(original.get('candidates'), list)
            or type(include_candidates) is not bool
            or (max_source_distance_um is not None
                and (type(max_source_distance_um) not in (int, float)
                     or not math.isfinite(max_source_distance_um)
                     or max_source_distance_um < 0))):
        raise ValueError('Incompatible output diagnostic identity')
    times = np.asarray(solution.get('time_ms'), dtype=float)
    ids = np.asarray(solution.get('edge_node_ids'))
    voltage = np.asarray(solution.get('voltage_mv'), dtype=float)
    if (times.ndim != 1 or len(times) < 2 or ids.ndim != 1
            or ids.dtype.kind not in 'iu' or voltage.shape != (len(ids), len(times))
            or not np.isfinite(voltage).all()):
        raise ValueError('Invalid feedback output solution')
    config = provenance.get('configuration', {})
    overrides = config.get('nseg_by_edge') if isinstance(config, dict) else None
    remeshed = overrides is not None or (isinstance(config, dict)
                                         and config.get('nseg_per_edge', 1) != 1)
    edge_ranges = {}
    if remeshed:
        if overrides is None:
            overrides = {}
        default = config.get('nseg_per_edge')
        if (not isinstance(overrides, dict) or type(default) is not int or default < 1
                or default % 2 != 1 or any(
                    type(key) is not str or not key.isascii() or not key.isdigit()
                    or str(int(key)) != key or int(key) <= 0
                    or type(value) is not int or value < 1 or value % 2 != 1
                    for key, value in overrides.items())):
            raise ValueError('Invalid feedback output discretization')
        for index, value in enumerate(ids):
            child = int(value)
            if child not in edge_ranges:
                edge_ranges[child] = [index, 1]
            else:
                start, count = edge_ranges[child]
                if index != start + count:
                    raise ValueError('Noncontiguous feedback output compartments')
                edge_ranges[child][1] += 1
        if any(int(key) not in edge_ranges for key in overrides):
            raise ValueError('Unknown feedback output edge')
        if any(count != overrides.get(str(child), default)
               for child, (_, count) in edge_ranges.items()):
            raise ValueError('Feedback output discretization mismatch')
    events = Counter()
    positions, local_events, seen = {}, [], {}
    for candidate in original['candidates']:
        if candidate.get('included_in_graph') is not True:
            continue
        if max_source_distance_um is not None:
            distance = candidate.get('centerline_distance_um')
            if (type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0):
                raise ValueError('Invalid verified source geometry')
            if distance > max_source_distance_um:
                continue
        index = candidate.get('result_segment_index')
        child = candidate.get('child_node_id')
        partner = candidate.get('partner_id')
        if remeshed:
            fraction = candidate.get('segment_fraction')
            if (type(child) is not int or child not in edge_ranges
                    or type(fraction) not in (int, float) or not math.isfinite(fraction)
                    or not 0 <= fraction <= 1):
                raise ValueError('Missing verified output position for remeshed cell')
            start, count = edge_ranges[child]
            index = start + min(int(fraction * count), count - 1)
        if (type(index) is not int or not 0 <= index < len(ids) or type(child) is not int
                or int(ids[index]) != child or not isinstance(partner, str)
                or not partner.isascii() or not partner.isdigit() or partner.startswith('0')):
            raise ValueError('Invalid verified output compartment')
        if index not in positions:
            positions[index] = threshold_crossing_ticks(times, voltage[index],
                threshold_mv=threshold_mv, duration_ms=duration_ms)
        if include_candidates:
            point = candidate.get('source_position_8nm')
            if (not isinstance(point, list) or len(point) != 3
                    or any(type(value) is not int for value in point)):
                raise ValueError('Missing source coordinate')
            identity = (partner, *point)
            # Distinct registered synapses may share a presynaptic coordinate.
            # Preserve their multiplicity only if they map to the same segment.
            if identity in seen and seen[identity] != index:
                raise ValueError('Conflicting duplicate source coordinate')
            seen[identity] = index
            local_events.append({'source_position_8nm': point.copy(), 'partner_id': partner,
                                 'stimulated_ticks_ms': [int(tick) for tick in positions[index]]})
        for tick in positions[index]:
            events[(int(partner), int(tick))] += 1
    edge_events = [{'source_id': body, 'target_id': target, 'tick': tick, 'count': count}
                   for (target, tick), count in sorted(events.items())]
    if include_candidates:
        return {'edge_events': edge_events, 'candidates': local_events}
    return edge_events
