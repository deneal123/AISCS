"""Map observed LIF spikes onto verified incoming synapse candidates.

Geometry is candidate-level only. The graph's predicted sign does not prove a
postsynaptic receptor type or a calibrated conductance.
"""

from __future__ import annotations

import math
from collections import defaultdict

from service.infrastructure.connectome.synapse_morphology import (
    registered_incoming_candidates_single_pass,
)


def map_lif_feedback(graph, index, directories, feedback, source_ids, *, max_distance_um,
                     allow_partial=False, _geometry_cache=None):
    if (not isinstance(feedback, dict)
            or feedback.get('graph_sha256') != graph.provenance.get('manifest_sha256')
            or not isinstance(feedback.get('events'), list)
            or not isinstance(source_ids, list) or not source_ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or type(allow_partial) is not bool or isinstance(max_distance_um, bool)
            or not isinstance(max_distance_um, int | float)
            or not math.isfinite(max_distance_um) or max_distance_um < 0):
        raise ValueError('Invalid LIF feedback mapping inputs')
    forced = set(source_ids)
    groups = defaultdict(lambda: defaultdict(list))
    for item in feedback['events']:
        if not isinstance(item, dict):
            raise ValueError('Invalid feedback event')
        if item.get('kind') != 'lif-network-spike':
            continue
        source, target = item.get('source_id'), item.get('target_id')
        tick, count = item.get('emission_tick_ms'), item.get('synapse_count')
        if (type(source) is not int or source <= 0 or source in forced or target not in forced
                or type(tick) is not int or tick <= 0 or type(count) is not int or count <= 0):
            raise ValueError('Invalid LIF feedback event')
        groups[target][source].append(item)
    mappings = []
    for target, partners in groups.items():
        # This cache is private to one iteration run. Only immutable geometry is
        # reused; spike times are always read from the current feedback below.
        key = (id(graph), id(index), tuple(map(str, directories)), target,
               tuple(sorted(partners)))
        result = None if _geometry_cache is None else _geometry_cache.get(key)
        if result is None and _geometry_cache is not None:
            # A validated superset already contains every requested candidate.
            # Partner times are applied below, never stored in this cache.
            requested = set(key[-1])
            for cached_key, cached_result in _geometry_cache.items():
                if cached_key[:4] == key[:4] and requested.issubset(cached_key[-1]):
                    result = cached_result
                    break
        if result is None:
            result = registered_incoming_candidates_single_pass(
                index, graph, target, directories, candidate_partner_ids=set(partners))
        if (result.get('body_id') != str(target) or result.get('direction') != 'incoming'
                or result.get('graph_manifest_sha256') != feedback['graph_sha256']
                or result.get('complete_graph_edge_coverage') is not True
                or not isinstance(result.get('candidates'), list)):
            raise ValueError('Invalid incoming mapping identity')
        if _geometry_cache is not None:
            _geometry_cache[key] = result
        for source, events in partners.items():
            rows = [row for row in result['candidates'] if row.get('partner_id') == str(source)]
            ticks = [event['emission_tick_ms'] for event in events]
            if (not rows or len(set(ticks)) != len(ticks)
                    or any(event['synapse_count'] != len(rows) for event in events)):
                raise ValueError('LIF events disagree with registered synapse coverage')
            candidates, unresolved = [], []
            for row in rows:
                distance = row.get('centerline_distance_um')
                if (isinstance(distance, bool) or not isinstance(distance, int | float)
                        or not math.isfinite(distance) or distance < 0):
                    raise ValueError('Invalid candidate distance')
                candidate = {'target_child_node_id': row['child_node_id'],
                             'target_fraction': row['segment_fraction'],
                             'target_position_8nm': row['source_position_8nm'],
                             'target_distance_um': distance, 'stimulated_ticks_ms': sorted(ticks)}
                if 'presynaptic_position_8nm' in row:
                    candidate['source_position_8nm'] = row['presynaptic_position_8nm']
                if distance <= max_distance_um:
                    candidates.append(candidate)
                elif allow_partial:
                    unresolved.append(candidate)
                else:
                    raise ValueError('Unresolved LIF feedback geometry')
            mapping = {'source_id': source, 'target_id': target,
                       'input_kind': 'lif-network-spike', 'graph_sha256': feedback['graph_sha256'],
                       'target_morphology_sha256': result['morphology_sha256'],
                       'source_md5': result['source_md5'], 'candidates': candidates,
                       'interpretation': 'candidate target geometry; no calibrated synaptic effect'}
            if unresolved:
                mapping['unresolved_target_geometry'] = unresolved
            mappings.append(mapping)
    return mappings
