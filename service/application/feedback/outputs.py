"""Re-evaluate registered source-output crossings after a feedback replay."""

from __future__ import annotations

import copy
import math
from collections import Counter

import numpy as np

from service.infrastructure.connectome.forced_network import threshold_crossing_ticks


def merge_archived_source_events(original, archived, *, control=None):
    """Attach archived crossing ticks to independently verified source diagnostics.

    This preserves the geometry and provenance required by pair mapping. The
    caller must authenticate all inputs and ensure a control uses the same
    geometry, time grid and parameters with the stimulus disabled.
    """
    if (not isinstance(original, dict) or not isinstance(original.get('candidates'), list)
            or type(original.get('duration_ms')) is not int or original['duration_ms'] < 1
            or not isinstance(archived, dict) or not isinstance(archived.get('candidates'), list)
            or not isinstance(archived.get('edge_events'), list)):
        raise ValueError('Invalid archived source diagnostics')
    by_key = {}
    for row in archived['candidates']:
        if (not isinstance(row, dict) or set(row) != {
                'source_position_8nm', 'partner_id', 'stimulated_ticks_ms'}
                or not isinstance(row['source_position_8nm'], list)
                or len(row['source_position_8nm']) != 3
                or any(type(v) is not int for v in row['source_position_8nm'])
                or not isinstance(row['partner_id'], str) or not row['partner_id'].isascii()
                or not row['partner_id'].isdigit() or row['partner_id'].startswith('0')
                or not isinstance(row['stimulated_ticks_ms'], list)
                or any(type(tick) is not int or not 1 <= tick <= original.get('duration_ms', 0)
                       for tick in row['stimulated_ticks_ms'])
                or row['stimulated_ticks_ms'] != sorted(set(row['stimulated_ticks_ms']))):
            raise ValueError('Invalid archived source candidate')
        key = (row['partner_id'], *row['source_position_8nm'])
        if key in by_key and by_key[key][0] != row['stimulated_ticks_ms']:
            raise ValueError('Conflicting archived source candidate')
        by_key.setdefault(key, []).append(row['stimulated_ticks_ms'])
    updated = copy.deepcopy(original)
    expected = Counter()
    for row in updated['candidates']:
        if row.get('included_in_graph') is not True:
            continue
        key = (row.get('partner_id'), *row.get('source_position_8nm', []))
        if key not in by_key or not by_key[key]:
            raise ValueError('Missing archived source candidate')
        ticks = by_key[key].pop()
        if row.get('status') == 'geometry_unresolved' and ticks:
            raise ValueError('Unresolved source geometry cannot have observed events')
        unresolved = row.get('status') == 'geometry_unresolved'
        row['stimulated_ticks_ms'] = None if unresolved else ticks.copy()
        # The archived replay has no paired control. Old control values and
        # classifications belong to another replay and must not be reused.
        row['control_ticks_ms'] = None
        row['status'] = 'geometry_unresolved' if unresolved else 'timing_or_trace_ambiguous'
        row.pop('stimulated_crossing_intervals', None)
        row.pop('control_crossing_intervals', None)
        for field in ('max_stimulated_mv', 'max_control_mv', 'max_abs_delta_mv'):
            row.pop(field, None)
        for tick in ticks:
            expected[(int(row['partner_id']), tick)] += 1
    if any(rows for rows in by_key.values()):
        raise ValueError('Unexpected archived source candidate')
    body = original.get('body_id')
    try:
        expected_events = [{'source_id': int(body), 'target_id': target, 'tick': tick,
                            'count': count}
                           for (target, tick), count in sorted(expected.items())]
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid archived source identity') from exc
    if archived['edge_events'] != expected_events:
        raise ValueError('Archived edge events do not match candidates')
    if control is not None:
        control_rows = merge_archived_source_events(original, control)['candidates']
        for row, quiet in zip(updated['candidates'], control_rows, strict=True):
            if row.get('included_in_graph') is not True or row['status'] == 'geometry_unresolved':
                continue
            ticks, control_ticks = row['stimulated_ticks_ms'], quiet['stimulated_ticks_ms']
            row['control_ticks_ms'] = control_ticks
            row['status'] = ('control_crossing' if control_ticks else
                             'stimulus_only_crossing' if ticks else 'no_crossing')
    return updated


def feedback_output_events(body, solution, provenance, original, *, threshold_mv, duration_ms,
                           include_candidates=False, max_source_distance_um=None):
    """Extract model edge events at previously verified outgoing compartments.

    Original geometry must already have passed fragment archive verification.
    This function does not infer that fragmented morphology is connected.
    """
    return _feedback_output_events(body, solution, provenance, original, threshold_mv=threshold_mv,
        duration_ms=duration_ms, include_candidates=include_candidates,
        max_source_distance_um=max_source_distance_um, indices_only=False, selected_traces=None)


def feedback_output_segment_indices(body, edge_node_ids, provenance, original, *, threshold_mv,
                                    duration_ms, max_source_distance_um=None):
    """Resolve selected output segments using the same verified candidate rules.

    The caller must verify the source archive and morphology before calling.
    Returned indices identify numerical compartments, not biological synapses.
    """
    return _feedback_output_events(body, {'edge_node_ids': edge_node_ids}, provenance, original,
        threshold_mv=threshold_mv, duration_ms=duration_ms, include_candidates=False,
        max_source_distance_um=max_source_distance_um, indices_only=True, selected_traces=None)


def feedback_selected_output_events(body, time_ms, edge_node_ids, traces, provenance, original, *,
                                    threshold_mv, duration_ms, include_candidates=False,
                                    max_source_distance_um=None):
    """Evaluate verified candidate traces without a full segment-by-time matrix."""
    return _feedback_output_events(body, {'time_ms': time_ms, 'edge_node_ids': edge_node_ids},
        provenance, original, threshold_mv=threshold_mv, duration_ms=duration_ms,
        include_candidates=include_candidates, max_source_distance_um=max_source_distance_um,
        indices_only=False, selected_traces=traces)


def feedback_selected_output_ticks(body, edge_node_ids, ticks, provenance, original, *,
                                   threshold_mv, duration_ms, include_candidates=False,
                                   include_unresolved_candidates=False,
                                   max_source_distance_um=None):
    """Map already validated streaming crossings to verified candidate edges."""
    return _feedback_output_events(body, {'edge_node_ids': edge_node_ids}, provenance, original,
        threshold_mv=threshold_mv, duration_ms=duration_ms, include_candidates=include_candidates,
        max_source_distance_um=max_source_distance_um, indices_only=False, selected_traces=None,
        selected_ticks=ticks, include_unresolved_candidates=include_unresolved_candidates)


def _feedback_output_events(body, solution, provenance, original, *, threshold_mv, duration_ms,
                            include_candidates, max_source_distance_um, indices_only,
                            selected_traces, selected_ticks=None,
                            include_unresolved_candidates=False):
    if (type(body) is not int or body <= 0 or not isinstance(original, dict)
            or original.get('body_id') != str(body) or provenance.get('body_id') != str(body)
            or provenance.get('morphology_sha256') != original.get('morphology_sha256')
            or original.get('threshold_mv') != threshold_mv
            or original.get('duration_ms') != duration_ms
            or not isinstance(original.get('candidates'), list)
            or type(include_candidates) is not bool
            or type(include_unresolved_candidates) is not bool
            or (include_unresolved_candidates and not include_candidates)
            or (max_source_distance_um is not None
                and (type(max_source_distance_um) not in (int, float)
                     or not math.isfinite(max_source_distance_um)
                     or max_source_distance_um < 0))):
        raise ValueError('Incompatible output diagnostic identity')
    ids = np.asarray(solution.get('edge_node_ids'))
    if ids.ndim != 1 or ids.dtype.kind not in 'iu':
        raise ValueError('Invalid feedback output solution')
    if selected_ticks is not None:
        if (not isinstance(selected_ticks, dict)
                or any(type(index) is not int or not 0 <= index < len(ids)
                       or not isinstance(ticks, list)
                       or any(type(tick) is not int or not 1 <= tick <= duration_ms
                              for tick in ticks)
                       or ticks != sorted(set(ticks)) for index, ticks in selected_ticks.items())):
            raise ValueError('Invalid selected feedback ticks')
    elif not indices_only:
        times = np.asarray(solution.get('time_ms'), dtype=float)
        if times.ndim != 1 or len(times) < 2:
            raise ValueError('Invalid feedback output solution')
        if selected_traces is None:
            voltage = np.asarray(solution.get('voltage_mv'), dtype=float)
            if voltage.shape != (len(ids), len(times)) or not np.isfinite(voltage).all():
                raise ValueError('Invalid feedback output solution')
        else:
            if (not isinstance(selected_traces, dict)
                    or any(type(index) is not int or not 0 <= index < len(ids)
                           or np.asarray(trace).shape != times.shape
                           or not np.isfinite(np.asarray(trace, dtype=float)).all()
                           for index, trace in selected_traces.items())):
                raise ValueError('Invalid selected feedback traces')
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
        if (include_unresolved_candidates and candidate.get('status') == 'geometry_unresolved'
                and (max_source_distance_um is None
                     or type(candidate.get('centerline_distance_um')) not in (int, float)
                     or candidate['centerline_distance_um'] <= max_source_distance_um)):
            raise ValueError('Unresolved source candidate requires matching distance cutoff')
        if max_source_distance_um is not None:
            distance = candidate.get('centerline_distance_um')
            if (type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0):
                raise ValueError('Invalid verified source geometry')
            if distance > max_source_distance_um:
                if include_unresolved_candidates:
                    point = candidate.get('source_position_8nm')
                    partner = candidate.get('partner_id')
                    if (candidate.get('status') != 'geometry_unresolved'
                            or not isinstance(point, list) or len(point) != 3
                            or any(type(value) is not int or value < 0 for value in point)
                            or not isinstance(partner, str) or not partner.isascii()
                            or not partner.isdigit() or partner.startswith('0')):
                        raise ValueError('Invalid unresolved source candidate')
                    # Placeholder only: the original geometry_unresolved status
                    # prevents treating this as an observed negative crossing.
                    local_events.append({'source_position_8nm': point.copy(),
                                         'partner_id': partner, 'stimulated_ticks_ms': []})
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
            if selected_traces is not None and index not in selected_traces:
                raise ValueError('Missing selected feedback trace')
            if selected_ticks is not None:
                if index not in selected_ticks:
                    raise ValueError('Missing selected feedback ticks')
                positions[index] = selected_ticks[index]
            else:
                positions[index] = ([] if indices_only else threshold_crossing_ticks(
                    times, voltage[index] if selected_traces is None else selected_traces[index],
                    threshold_mv=threshold_mv, duration_ms=duration_ms))
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
    if indices_only:
        return list(positions)
    if selected_traces is not None and set(selected_traces) != set(positions):
        raise ValueError('Unexpected selected feedback trace')
    if selected_ticks is not None and set(selected_ticks) != set(positions):
        raise ValueError('Unexpected selected feedback ticks')
    edge_events = [{'source_id': body, 'target_id': target, 'tick': tick, 'count': count}
                   for (target, tick), count in sorted(events.items())]
    if include_candidates:
        return {'edge_events': edge_events, 'candidates': local_events}
    return edge_events
