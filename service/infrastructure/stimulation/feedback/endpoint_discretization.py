"""Explicit bounded finite-volume approximation for endpoint synapses.

This module does not select a tolerance or run a solver. The reported shift is
from the projected cable endpoint, not from the original synapse observation.
It is not a physiological or signal-error bound.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np


def audit_effective_positions(events, edges_um, observations_um, resolutions):
    """Report finite-segment locations for all events without changing them.

    NEURON associates an interior point process with its containing segment.
    For exact endpoints this reports the *proposed* nearest center: an endpoint
    remains a zero-area node unless the caller explicitly relocates it. The
    distances are geometric, and callers must justify their own error bounds.
    """
    if (not isinstance(events, list) or not isinstance(edges_um, dict)
            or not isinstance(observations_um, list) or len(events) != len(observations_um)
            or not isinstance(resolutions, dict)):
        raise ValueError('Invalid effective position inputs')
    result = []
    for index, (event, observation) in enumerate(zip(events, observations_um, strict=True)):
        if not isinstance(event, dict) or type(event.get('child_node_id')) is not int:
            raise ValueError('Invalid effective position event')
        node = event['child_node_id']
        position = event.get('position')
        count = resolutions.get(node)
        if (node <= 0 or type(position) not in (int, float) or not math.isfinite(position)
                or not 0 <= position <= 1 or type(count) is not int or count < 1
                or count % 2 != 1):
            raise ValueError('Invalid effective position event or resolution')
        edge = np.asarray(edges_um.get(node), dtype=float)
        point = np.asarray(observation, dtype=float)
        if (edge.shape != (2, 3) or point.shape != (3,)
                or not np.isfinite(edge).all() or not np.isfinite(point).all()):
            raise ValueError('Invalid effective position geometry')
        length = float(np.linalg.norm(edge[1] - edge[0]))
        if not math.isfinite(length) or length <= 0:
            raise ValueError('Invalid effective position edge')
        segment = min(int(position * count), count - 1)
        effective = (segment + .5) / count
        center = edge[0] + effective * (edge[1] - edge[0])
        distance = float(np.linalg.norm(point - center))
        if not math.isfinite(distance):
            raise ValueError('Invalid effective position distance')
        result.append({'event_index': index, 'child_node_id': node, 'nseg': count,
                       'original_position': float(position), 'effective_position': effective,
                       'requires_endpoint_relocation': position in (0, 1),
                       'shift_um': abs(position - effective) * length,
                       'observation_distance_um': distance})
    return result


def discretize_endpoints(events, edges_um, *, nseg_per_edge, max_shift_um,
                         observations_um=None, max_observation_distance_um=None):
    """Return copied events and endpoint-mapping evidence, or reject the batch.

    ``edges_um`` maps child node IDs to pairs of verified start/end coordinates
    in micrometres. An endpoint is mapped to the center of the nearest finite
    segment on its explicitly selected edge. No choice of edge is inferred.
    Optional observations are paired one-for-one with events. When supplied,
    each endpoint's distance from observation to effective center is checked
    separately; it is not estimated from the endpoint shift alone. Interior
    events are unchanged and require their own observation-distance validation.
    """
    if (not isinstance(events, list) or not isinstance(edges_um, dict)
            or type(nseg_per_edge) is not int or nseg_per_edge < 1 or nseg_per_edge % 2 != 1
            or isinstance(max_shift_um, bool) or not isinstance(max_shift_um, int | float)
            or not math.isfinite(max_shift_um) or max_shift_um < 0):
        raise ValueError('Invalid endpoint discretization settings')
    if (observations_um is None) != (max_observation_distance_um is None):
        raise ValueError('Observation positions and distance limit must be supplied together')
    if observations_um is not None:
        if (not isinstance(observations_um, list) or len(observations_um) != len(events)
                or isinstance(max_observation_distance_um, bool)
                or not isinstance(max_observation_distance_um, int | float)
                or not math.isfinite(max_observation_distance_um)
                or max_observation_distance_um < 0):
            raise ValueError('Invalid endpoint observation settings')
    mapped, evidence = [], []
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or type(event.get('child_node_id')) is not int
                or event['child_node_id'] <= 0):
            raise ValueError('Invalid endpoint event')
        position = event.get('position')
        if (isinstance(position, bool) or not isinstance(position, int | float)
                or not math.isfinite(position) or not 0 <= position <= 1):
            raise ValueError('Invalid endpoint event position')
        row = event.copy()
        if position in (0, 1):
            coords = np.asarray(edges_um.get(event['child_node_id']), dtype=float)
            if coords.shape != (2, 3) or not np.isfinite(coords).all():
                raise ValueError('Missing or invalid endpoint edge geometry')
            length = float(np.linalg.norm(coords[1] - coords[0]))
            if not math.isfinite(length) or length <= 0:
                raise ValueError('Invalid endpoint edge length')
            shift = length / (2 * nseg_per_edge)
            if not math.isfinite(shift) or shift > max_shift_um:
                raise ValueError('Endpoint discretization exceeds explicit displacement limit')
            effective = .5 / nseg_per_edge if position == 0 else 1 - .5 / nseg_per_edge
            row['position'] = effective
            item = {'event_index': index, 'child_node_id': event['child_node_id'],
                    'original_position': float(position), 'effective_position': effective,
                    'shift_um': shift, 'nseg_per_edge': nseg_per_edge}
            if observations_um is not None:
                observation = np.asarray(observations_um[index], dtype=float)
                if observation.shape != (3,) or not np.isfinite(observation).all():
                    raise ValueError('Invalid endpoint observation position')
                center = coords[0] + effective * (coords[1] - coords[0])
                observation_distance = float(np.linalg.norm(observation - center))
                if (not math.isfinite(observation_distance)
                        or observation_distance > max_observation_distance_um):
                    raise ValueError('Effective endpoint exceeds observation distance limit')
                item['observation_um'] = observation.tolist()
                item['observation_distance_um'] = observation_distance
            evidence.append(item)
        mapped.append(row)
    return mapped, evidence


def choose_endpoint_resolutions(events, edges_um, observations_um, *, max_shift_um,
                                max_observation_distance_um, max_nseg):
    """Find the smallest allowed odd segment count per affected edge.

    This only establishes geometry, not solution convergence. Every event on
    a remeshed edge, including interior events, must satisfy the supplied
    observation-distance bound. No scientific bound is chosen here.
    """
    if (not isinstance(events, list) or not isinstance(observations_um, list)
            or len(events) != len(observations_um) or type(max_nseg) is not int
            or max_nseg < 1 or max_nseg % 2 != 1):
        raise ValueError('Invalid adaptive endpoint settings')
    discretize_endpoints(
        [], edges_um, nseg_per_edge=1, max_shift_um=max_shift_um, observations_um=[],
        max_observation_distance_um=max_observation_distance_um)
    groups = {}
    for index, event in enumerate(events):
        if (not isinstance(event, dict) or type(event.get('child_node_id')) is not int
                or event['child_node_id'] <= 0 or type(event.get('position')) not in (int, float)
                or not math.isfinite(event['position']) or not 0 <= event['position'] <= 1):
            raise ValueError('Invalid adaptive endpoint event')
        groups.setdefault(event['child_node_id'], []).append(index)
    selected = {}
    for child, indices in groups.items():
        if not any(events[index]['position'] in (0, 1) for index in indices):
            continue
        subset = [events[index] for index in indices if events[index]['position'] in (0, 1)]
        observations = [observations_um[index] for index in indices
                        if events[index]['position'] in (0, 1)]
        for nseg in range(1, max_nseg + 1, 2):
            try:
                _, evidence = discretize_endpoints(
                    subset, edges_um, nseg_per_edge=nseg, max_shift_um=max_shift_um,
                    observations_um=observations,
                    max_observation_distance_um=max_observation_distance_um)
            except ValueError as exc:
                if str(exc) in ('Endpoint discretization exceeds explicit displacement limit',
                                'Effective endpoint exceeds observation distance limit'):
                    continue
                raise
            all_evidence = audit_effective_positions(
                [events[index] for index in indices], edges_um,
                [observations_um[index] for index in indices], {child: nseg})
            if any(row['observation_distance_um'] > max_observation_distance_um
                   for row in all_evidence):
                continue
            selected[child] = {'nseg': nseg, 'endpoints': len(subset),
                               'max_shift_um': max(row['shift_um'] for row in evidence),
                               'max_observation_distance_um': max(
                                   row['observation_distance_um'] for row in all_evidence)}
            break
        else:
            raise ValueError('No endpoint resolution satisfies explicit limits')
    return selected


def prepare_discretized_events(events, edges_um, observations_um, *, max_shift_um,
                               max_observation_distance_um, max_nseg):
    """Prepare a bounded replay with an auditable original-to-effective mapping.

    The caller must independently verify the source observations and justify
    the explicit bounds. This does not establish physiological validity or
    numerical convergence, and does not modify the supplied events.
    """
    selected = choose_endpoint_resolutions(
        events, edges_um, observations_um, max_shift_um=max_shift_um,
        max_observation_distance_um=max_observation_distance_um, max_nseg=max_nseg)
    counts = {event['child_node_id']: selected.get(event['child_node_id'], {}).get('nseg', 1)
              for event in events}
    evidence = audit_effective_positions(events, edges_um, observations_um, counts)
    if any(row['observation_distance_um'] > max_observation_distance_um for row in evidence):
        raise ValueError('Effective event exceeds observation distance limit')
    mapped = []
    for index, event in enumerate(events):
        item = event.copy()
        if evidence[index]['requires_endpoint_relocation']:
            item['position'] = evidence[index]['effective_position']
        mapped.append(item)
    payload = {'original_events': [event.copy() for event in events],
               'effective_events': mapped, 'evidence': evidence,
               'observations_um': [np.asarray(point, dtype=float).tolist()
                                   for point in observations_um],
               'edges_um': {str(key): np.asarray(edges_um[key], dtype=float).tolist()
                            for key in counts},
               'nseg_by_edge': {str(key): value['nseg'] for key, value in selected.items()},
               'limits': {'max_shift_um': max_shift_um,
                          'max_observation_distance_um': max_observation_distance_um,
                          'max_nseg': max_nseg}}
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                               allow_nan=False).encode('utf8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid discretization provenance') from exc
    return {**payload, 'sha256': hashlib.sha256(canonical).hexdigest(),
            'interpretation': ('bounded geometric approximation; '
                               'not numerical or biological validation')}


def validate_prepared_events(prepared, original_events, edges_um, observations_um, *,
                             max_shift_um, max_observation_distance_um, max_nseg):
    """Recompute a prepared mapping from caller-verified geometry and limits.

    A checksum alone does not prove that an event belongs to a particular
    synapse or morphology. Callers must authenticate those inputs separately.
    """
    if not isinstance(prepared, dict):
        raise ValueError('Invalid prepared discretization')
    expected = prepare_discretized_events(
        original_events, edges_um, observations_um, max_shift_um=max_shift_um,
        max_observation_distance_um=max_observation_distance_um, max_nseg=max_nseg)
    if prepared != expected:
        raise ValueError('Prepared discretization does not match verified inputs')
    return expected


def prepare_shared_discretization(conditions, edges_um, *, max_shift_um,
                                  max_observation_distance_um, max_nseg):
    """Prepare one grid from every condition, preserving each event's origin.

    The caller authenticates the event observations and chooses the limits.
    A shared grid avoids comparing signals from independently remeshed cells;
    it does not establish numerical convergence or biological validity.
    """
    if (not isinstance(conditions, dict) or not conditions
            or any(not isinstance(key, str) or not key for key in conditions)):
        raise ValueError('Invalid shared discretization conditions')
    events, observations, slices = [], [], {}
    for name in sorted(conditions):
        condition = conditions[name]
        if (not isinstance(condition, dict) or set(condition) != {'events', 'observations_um'}
                or not isinstance(condition['events'], list)
                or not isinstance(condition['observations_um'], list)
                or len(condition['events']) != len(condition['observations_um'])):
            raise ValueError('Invalid shared discretization condition')
        start = len(events)
        events.extend(condition['events'])
        observations.extend(condition['observations_um'])
        slices[name] = (start, len(events))
    prepared = prepare_discretized_events(events, edges_um, observations,
        max_shift_um=max_shift_um, max_observation_distance_um=max_observation_distance_um,
        max_nseg=max_nseg)
    return {'shared': prepared, 'conditions': {
        name: {'effective_events': prepared['effective_events'][start:end],
               'evidence': prepared['evidence'][start:end]}
        for name, (start, end) in slices.items()},
        'interpretation': 'shared bounded geometric approximation; not validated dynamics'}


def merge_shared_grid_requirements(previous, proposed, *, max_nseg):
    """Merge verified grid requirements without silently coarsening an edge.

    A changed grid invalidates both conditions' old traces; callers must replay
    both before drawing a comparison. Merging counts does not itself validate
    positions on the resulting grid; every observation must be audited again.
    """
    if (not isinstance(previous, dict) or not isinstance(proposed, dict)
            or type(max_nseg) is not int or max_nseg < 1 or max_nseg % 2 != 1):
        raise ValueError('Invalid shared grid requirements')
    for grid in (previous, proposed):
        if any(not isinstance(key, str) or not key.isascii() or not key.isdigit()
               or key.startswith('0') or type(value) is not int or value < 1
               or value > max_nseg or value % 2 != 1 for key, value in grid.items()):
            raise ValueError('Invalid shared grid requirement')
    canonical_previous = {child: nseg for child, nseg in previous.items() if nseg > 1}
    merged = canonical_previous.copy()
    for child, nseg in proposed.items():
        if nseg > 1:
            merged[child] = max(merged.get(child, 1), nseg)
    return {'nseg_by_edge': merged, 'restart_required': merged != canonical_previous,
            'requires_observation_reaudit': True,
            'interpretation': 'grid plan only; both conditions require replay after changes'}


def apply_shared_grid(conditions, edges_um, grid, *, max_shift_um,
                      max_observation_distance_um, max_nseg):
    """Recheck every event on an explicitly fixed grid shared across conditions.

    Input observations and morphology must be independently authenticated.
    This is a geometric check, not an estimate of numerical or biological error.
    """
    checked_grid = merge_shared_grid_requirements({}, grid, max_nseg=max_nseg)['nseg_by_edge']
    if (not isinstance(conditions, dict) or not conditions
            or any(not isinstance(name, str) or not name for name in conditions)
            or type(max_shift_um) not in (int, float) or not math.isfinite(max_shift_um)
            or max_shift_um < 0 or type(max_observation_distance_um) not in (int, float)
            or not math.isfinite(max_observation_distance_um) or max_observation_distance_um < 0):
        raise ValueError('Invalid shared grid audit')
    output = {}
    for name, condition in conditions.items():
        if (not isinstance(condition, dict) or set(condition) != {'events', 'observations_um'}
                or not isinstance(condition['events'], list)
                or not isinstance(condition['observations_um'], list)
                or len(condition['events']) != len(condition['observations_um'])):
            raise ValueError('Invalid shared grid condition')
        events, observations = condition['events'], condition['observations_um']
        counts = {event['child_node_id']: checked_grid.get(str(event['child_node_id']), 1)
                  for event in events if isinstance(event, dict) and 'child_node_id' in event}
        evidence = audit_effective_positions(events, edges_um, observations, counts)
        if any(row['observation_distance_um'] > max_observation_distance_um
               or (row['requires_endpoint_relocation'] and row['shift_um'] > max_shift_um)
               for row in evidence):
            raise ValueError('Shared grid exceeds explicit geometry limits')
        effective = []
        for event, row in zip(events, evidence, strict=True):
            copy = event.copy()
            if row['requires_endpoint_relocation']:
                copy['position'] = row['effective_position']
            effective.append(copy)
        output[name] = {'effective_events': effective, 'evidence': evidence}
    return {'nseg_by_edge': checked_grid, 'conditions': output,
            'interpretation': 'fixed shared grid geometrically audited; not validated dynamics'}
