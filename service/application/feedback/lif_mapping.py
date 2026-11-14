"""Map observed LIF spikes onto verified incoming synapse candidates.

Geometry is candidate-level only. The graph's predicted sign does not prove a
postsynaptic receptor type or a calibrated conductance.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from service.infrastructure.connectome.synapse_morphology import (
    registered_incoming_candidates_single_pass,
)


def map_lif_feedback(graph, index, directories, feedback, source_ids, *, max_distance_um,
                     allow_partial=False, _geometry_cache=None, experimental_spatial_index=False):
    if (not isinstance(feedback, dict)
            or feedback.get('graph_sha256') != graph.provenance.get('manifest_sha256')
            or not isinstance(feedback.get('events'), list)
            or not isinstance(source_ids, list) or not source_ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or type(allow_partial) is not bool or type(experimental_spatial_index) is not bool
            or isinstance(max_distance_um, bool)
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
    incoming_batches = None
    source_scans = None
    batch_targets = list(groups)
    if experimental_spatial_index and len(batch_targets) > 1:
        from service.infrastructure.connectome.neighbors import incoming_edge_indices_many
        from service.infrastructure.connectome.synapse_index import SynapseBatchIndex
        if _geometry_cache and isinstance(index, SynapseBatchIndex):
            index.assert_unchanged()

    cached_by_target = defaultdict(list)
    if _geometry_cache is not None:
        for cached_key, cached_result in _geometry_cache.items():
            cached_by_target[cached_key[:4]].append((cached_key[-1], cached_result))

    def cached_mapping(target, partners):
        key = (id(graph), id(index), tuple(map(str, directories)), target,
               tuple(sorted(partners)))
        if _geometry_cache is None:
            return key, None
        result = _geometry_cache.get(key)
        if result is None:
            requested = set(key[-1])
            for cached_partners, cached_result in cached_by_target[key[:4]]:
                if requested.issubset(cached_partners):
                    return key, cached_result
        return key, result

    reverse_edges = None
    if experimental_spatial_index and len(batch_targets) >= 1024:
        uncached_count = sum(cached_mapping(target, groups[target])[1] is None
                             for target in batch_targets)
        if uncached_count >= 1024:
            from service.infrastructure.connectome.reverse_edges import ReverseEdges
            reverse_edges = ReverseEdges(graph)

    for target_number, (target, partners) in enumerate(groups.items()):
        if experimental_spatial_index and len(batch_targets) > 1 and target_number % 64 == 0:
            # Bound simultaneous coordinate buffers without restricting the total workload.
            current_targets = [body for body in batch_targets[target_number:target_number + 64]
                               if cached_mapping(body, groups[body])[1] is None]
            if not current_targets:
                incoming_batches = {}
            elif reverse_edges is not None:
                incoming_batches = reverse_edges.incoming(current_targets)
            else:
                incoming_batches = incoming_edge_indices_many(graph, current_targets)
            source_scans = None
            if current_targets and isinstance(index, SynapseBatchIndex):
                requests = {}
                for current, indices in incoming_batches.items():
                    sources = np.searchsorted(graph.ptr, indices, side='right') - 1
                    requests[current] = ([int(graph.ids[source]) for source in sources],
                                         set(groups[current]))
                source_scans = index.scan_incoming_many(requests)
        # This cache is private to one iteration run. Only immutable geometry is
        # reused; spike times are always read from the current feedback below.
        key, result = cached_mapping(target, partners)
        if result is None:
            options = {'use_spatial_index': True} if experimental_spatial_index else {}
            if incoming_batches is not None:
                options['_incoming_edges'] = incoming_batches[target]
            if source_scans is not None:
                options['_incoming_scan'] = source_scans[target]
            result = registered_incoming_candidates_single_pass(
                index, graph, target, directories, candidate_partner_ids=set(partners), **options)
        if (result.get('body_id') != str(target) or result.get('direction') != 'incoming'
                or result.get('graph_manifest_sha256') != feedback['graph_sha256']
                or result.get('complete_graph_edge_coverage') is not True
                or not isinstance(result.get('candidates'), list)):
            raise ValueError('Invalid incoming mapping identity')
        if _geometry_cache is not None:
            _geometry_cache[key] = result
            cached_by_target[key[:4]].append((key[-1], result))
        rows_by_partner = defaultdict(list)
        for row in result['candidates']:
            if not isinstance(row, dict) or not isinstance(row.get('partner_id'), str):
                raise ValueError('Invalid incoming mapping candidate')
            rows_by_partner[row.get('partner_id')].append(row)
        for source, events in partners.items():
            rows = rows_by_partner[str(source)]
            ticks = [event['emission_tick_ms'] for event in events]
            if (not rows or len(set(ticks)) != len(ticks)
                    or any(event['synapse_count'] != len(rows) for event in events)):
                raise ValueError('LIF events disagree with registered synapse coverage')
            sorted_ticks = sorted(ticks)
            candidates, unresolved = [], []
            for row in rows:
                distance = row.get('centerline_distance_um')
                if (isinstance(distance, bool) or not isinstance(distance, int | float)
                        or not math.isfinite(distance) or distance < 0):
                    raise ValueError('Invalid candidate distance')
                candidate = {'target_child_node_id': row['child_node_id'],
                             'target_fraction': row['segment_fraction'],
                             'target_position_8nm': row['source_position_8nm'],
                             'target_distance_um': distance,
                             'stimulated_ticks_ms': sorted_ticks.copy()}
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
    if (experimental_spatial_index and len(batch_targets) > 1 and _geometry_cache
            and isinstance(index, SynapseBatchIndex)):
        index.assert_unchanged()
    return mappings
