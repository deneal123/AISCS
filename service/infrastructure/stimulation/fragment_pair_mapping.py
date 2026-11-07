"""Match exact indexed synapse pairs to candidate target compartments.

This is a geometric correspondence, not validated synaptic transmission.
"""

from __future__ import annotations

import math
from collections import Counter

from service.infrastructure.connectome.forced_network import validate_crossing_intervals
from service.infrastructure.connectome.fragment_mapping import map_fragment_candidates
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.connectome.neighbors import outgoing
from service.infrastructure.stimulation.fragment_output_diagnostics import fragment_edge_schedule


def match_fragment_inputs(diagnostics, index, graph, target_id, directories, *,
                          max_source_distance_um, max_target_distance_um, duration_ms,
                          allow_partial=False, allow_partial_source=False):
    """Match all pairs on one edge without inventing individual synapse identities."""
    if (type(target_id) is not int or target_id <= 0 or type(allow_partial) is not bool
            or type(allow_partial_source) is not bool):
        raise ValueError('Invalid target ID')
    if (isinstance(max_target_distance_um, bool)
            or not isinstance(max_target_distance_um, int | float)
            or not 0 <= max_target_distance_um < float('inf')):
        raise ValueError('Invalid target tolerance')
    schedule = fragment_edge_schedule(diagnostics, max_distance_um=max_source_distance_um,
                                      duration_ms=duration_ms,
                                      allow_partial_geometry=allow_partial_source)
    source_id = schedule['source_id']
    if source_id == target_id or schedule['graph_sha256'] != graph.provenance['manifest_sha256']:
        raise ValueError('Incompatible graph or source')
    edges = outgoing(graph, source_id, 0, len(graph.posts))
    if edges['next_offset'] is not None:
        raise ValueError('Incomplete graph edges')
    matching_edges = [item for item in edges['items'] if int(item['target_id']) == target_id]
    if len(matching_edges) != 1:
        raise ValueError('Target is not a unique registered edge')
    count = matching_edges[0]['synapse_count']
    selected = [row for row in diagnostics['candidates']
                if row['included_in_graph'] and row['partner_id'] == str(target_id)]
    page = index.query(target_id, 'incoming', limit=None, partner_ids=[source_id])
    rows = page['pairs']
    if (page['truncated'] or page['source_md5'] != diagnostics.get('source_md5')
            or page['total'] != count or page['returned'] != count
            or len(rows) != count or len(selected) != count
            or any(row.get('body_pre') != source_id or row.get('body_post') != target_id
                   or any(type(row.get(f'{axis}_{side}')) is not int
                          for axis in 'xyz' for side in ('pre', 'post')) for row in rows)):
        raise ValueError('Incomplete or inconsistent synapse pairs')
    keys = [tuple(row['source_position_8nm']) for row in selected]
    row_keys = [tuple(row[f'{axis}_pre'] for axis in 'xyz') for row in rows]
    if (any(len(key) != 3 or any(type(value) is not int for value in key) for key in keys)
            or Counter(keys) != Counter(row_keys)):
        raise ValueError('Ambiguous source coordinates')
    source_by_position = {}
    comparable = ('child_node_id', 'segment_fraction', 'result_segment_index',
                  'centerline_distance_um', 'status', 'stimulated_ticks_ms', 'control_ticks_ms',
                  'stimulated_crossing_intervals', 'control_crossing_intervals')
    for key, source in zip(keys, selected, strict=True):
        previous = source_by_position.get(key)
        if (previous is not None
                and any(previous.get(name) != source.get(name) for name in comparable)):
            raise ValueError('Conflicting duplicate source geometry or events')
        source_by_position[key] = source
    points = [[row[f'{axis}_post'] * .008 for axis in 'xyz'] for row in rows]
    skeleton = read_skeleton(target_id, directories)
    if skeleton.get('body_id') != str(target_id):
        raise ValueError('Target morphology identity mismatch')
    mapping = map_fragment_candidates(skeleton['swc'], points)
    candidates, unresolved, unresolved_source = [], [], []
    for row, child, fraction, distance in zip(
            rows, mapping['child_node_ids'], mapping['segment_fractions'],
            mapping['centerline_distances_um'], strict=True):
        source = source_by_position[tuple(row[f'{axis}_pre'] for axis in 'xyz')]
        if source['centerline_distance_um'] > max_source_distance_um:
            unresolved_source.append({
                'source_position_8nm': [row[f'{axis}_pre'] for axis in 'xyz'],
                'target_position_8nm': [row[f'{axis}_post'] for axis in 'xyz'],
                'source_distance_um': float(source['centerline_distance_um']),
            })
            continue
        if not math.isfinite(distance) or distance < 0:
            raise ValueError('Invalid target distance')
        if not 0 <= distance <= max_target_distance_um:
            if not allow_partial:
                raise ValueError('Unresolved target geometry')
            unresolved.append({'source_position_8nm': [row[f'{axis}_pre'] for axis in 'xyz'],
                               'target_position_8nm': [row[f'{axis}_post'] for axis in 'xyz'],
                               'target_distance_um': float(distance),
                               'stimulated_ticks_ms': source['stimulated_ticks_ms']})
            continue
        candidate = {'source_position_8nm': [row[f'{axis}_pre'] for axis in 'xyz'],
                     'target_position_8nm': [row[f'{axis}_post'] for axis in 'xyz'],
                     'target_child_node_id': child, 'target_fraction': float(fraction),
                     'target_distance_um': float(distance),
                     'stimulated_ticks_ms': source['stimulated_ticks_ms']}
        if 'stimulated_crossing_intervals' in source:
            candidate['stimulated_crossing_intervals'] = source['stimulated_crossing_intervals']
        candidates.append(candidate)
    result = {'source_id': source_id, 'target_id': target_id,
            'graph_sha256': schedule['graph_sha256'],
            'source_md5': page['source_md5'], 'target_morphology_sha256': skeleton['sha256'],
            'synapse_pairs': count, 'candidates': candidates,
            'interpretation': 'exact source-record correspondence and candidate target geometry; '
                              'not validated physiological transmission'}
    if unresolved:
        result['unresolved_target_geometry'] = unresolved
        result['interpretation'] = 'partial diagnostic only; unresolved geometry; not replayable'
    if unresolved_source:
        result['unresolved_source_geometry'] = unresolved_source
        result['interpretation'] = 'partial diagnostic only; unresolved geometry; not replayable'
    return result


def schedule_matched_fragment_events(mapping, *, delay_ms, duration_ms, weight_us,
                                     tau1_ms, tau2_ms, reversal_mv, max_events,
                                     timing_mode='tick'):
    """Apply explicit synaptic parameters only to each matched local output event."""
    numbers = (delay_ms, duration_ms, weight_us, tau1_ms, tau2_ms, reversal_mv)
    if (any(isinstance(value, bool) or not isinstance(value, int | float)
            or not math.isfinite(value) for value in numbers)
            or delay_ms < 0 or duration_ms <= 0 or weight_us <= 0
            or not 0 < tau1_ms < tau2_ms or not 1e-9 <= tau1_ms / tau2_ms <= .9999
            or type(max_events) is not int or max_events <= 0
            or timing_mode not in {'tick', 'upper_bound', 'lower_bound'}
            or not isinstance(mapping, dict) or not isinstance(mapping.get('candidates'), list)
            or 'unresolved_target_geometry' in mapping or 'unresolved_source_geometry' in mapping):
        raise ValueError('Invalid matched replay parameters')
    events, evidence, outside = [], [], 0
    for number, row in enumerate(mapping['candidates']):
        child, fraction, ticks = (row.get('target_child_node_id'), row.get('target_fraction'),
                                  row.get('stimulated_ticks_ms'))
        if (type(child) is not int or child <= 0 or isinstance(fraction, bool)
                or not isinstance(fraction, int | float) or not math.isfinite(fraction)
                or not 0 <= fraction <= 1 or not isinstance(ticks, list)
                or any(type(tick) is not int or not 1 <= tick <= duration_ms for tick in ticks)
                or any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))):
            raise ValueError('Invalid matched candidate')
        has_observation = 'target_position_8nm' in row or 'target_distance_um' in row
        source_point = row.get('source_position_8nm')
        if source_point is not None and (not has_observation or not isinstance(source_point, list)
                or len(source_point) != 3
                or any(type(value) is not int or value < 0 for value in source_point)):
            raise ValueError('Invalid source observation provenance')
        if has_observation:
            point, distance = row.get('target_position_8nm'), row.get('target_distance_um')
            if (not isinstance(point, list) or len(point) != 3
                    or any(type(value) is not int or value < 0 for value in point)
                    or type(distance) not in (int, float) or not math.isfinite(distance)
                    or distance < 0):
                raise ValueError('Invalid target observation provenance')
        intervals = row.get('stimulated_crossing_intervals')
        if timing_mode in {'upper_bound', 'lower_bound'}:
            if not ticks and intervals is None:
                intervals = []
            validate_crossing_intervals(intervals, ticks, duration_ms=duration_ms)
        for index, tick in enumerate(ticks):
            bound = 'upper_ms' if timing_mode == 'upper_bound' else 'lower_ms'
            source_time = tick if timing_mode == 'tick' else intervals[index][bound]
            arrival = source_time + delay_ms
            if arrival >= duration_ms:
                outside += 1
                continue
            if arrival <= 0:
                raise ValueError('Matched replay event at or before initial time')
            if len(events) >= max_events:
                raise ValueError('Matched replay exceeds event limit')
            events.append({'child_node_id': child, 'position': float(fraction), 'time_ms': arrival,
                           'weight_us': weight_us, 'tau1_ms': tau1_ms, 'tau2_ms': tau2_ms,
                           'reversal_mv': reversal_mv})
            item = {'candidate_index': number, 'source_tick_ms': tick}
            if has_observation:
                item['target_position_8nm'] = point.copy()
                item['target_distance_um'] = float(distance)
                if source_point is not None:
                    item['source_position_8nm'] = source_point.copy()
            if timing_mode in {'upper_bound', 'lower_bound'}:
                item['source_interval'] = dict(intervals[index])
            evidence.append(item)
    result = {'events': events, 'evidence': evidence, 'outside_window': outside,
              'interpretation': 'one-way candidate replay with explicit uncalibrated parameters'}
    if timing_mode != 'tick':
        result['timing_mode'] = timing_mode
    return result


def schedule_population_fragment_events(mappings, parameters, *, max_events, timing_mode='tick'):
    """Combine explicitly parameterised sources for one target, without feedback.

    Every mapping must describe the same graph and the same target morphology.
    The limit covers the complete population; no source is silently truncated.
    """
    if (not isinstance(mappings, list) or not mappings or len(mappings) > 256
            or not isinstance(parameters, list) or len(parameters) != len(mappings)
            or type(max_events) is not int or max_events <= 0):
        raise ValueError('Invalid population replay inputs')
    first = mappings[0]
    if not isinstance(first, dict):
        raise ValueError('Invalid population mapping')
    target = first.get('target_id')
    graph_sha = first.get('graph_sha256')
    morphology_sha = first.get('target_morphology_sha256')
    if (type(target) is not int or target <= 0
            or any(not isinstance(value, str) or len(value) != 64
                   or any(character not in '0123456789abcdef' for character in value)
                   for value in (graph_sha, morphology_sha))):
        raise ValueError('Invalid population target identity')
    seen, sources, events, evidence, outside, durations = set(), [], [], [], 0, set()
    for mapping, settings in zip(mappings, parameters, strict=True):
        if (not isinstance(mapping, dict) or type(mapping.get('source_id')) is not int
                or mapping['source_id'] <= 0 or mapping['source_id'] == target
                or mapping['source_id'] in seen or mapping.get('target_id') != target
                or mapping.get('graph_sha256') != graph_sha
                or mapping.get('target_morphology_sha256') != morphology_sha
                or not isinstance(settings, dict)
                or set(settings) != {'delay_ms', 'duration_ms', 'weight_us', 'tau1_ms',
                                     'tau2_ms', 'reversal_mv'}):
            raise ValueError('Incompatible population mapping or parameters')
        seen.add(mapping['source_id'])
        sources.append(mapping['source_id'])
        remaining = max_events - len(events)
        # The single-source validator requires a positive limit, including for
        # an empty schedule; still reject any new event if the budget is spent.
        result = schedule_matched_fragment_events(mapping, **settings, max_events=max(1, remaining),
                                                  timing_mode=timing_mode)
        durations.add(settings['duration_ms'])
        if len(result['events']) > remaining:
            raise ValueError('Population replay exceeds event limit')
        events.extend(result['events'])
        evidence.extend({'source_id': mapping['source_id'], **row} for row in result['evidence'])
        outside += result['outside_window']
    if len(durations) != 1:
        raise ValueError('Population replay durations differ')
    result = {'target_id': target, 'graph_sha256': graph_sha,
            'target_morphology_sha256': morphology_sha, 'source_ids': sources,
            'events': events, 'evidence': evidence, 'outside_window': outside,
            'interpretation': 'one-way uncalibrated candidate replay; no target feedback'}
    if timing_mode != 'tick':
        result['timing_mode'] = timing_mode
    return result
