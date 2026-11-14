"""Build source feedback candidates from a verified graph and prepared geometry.

The caller authenticates the graph, synapse index and packed morphology snapshot.
Nearest cable is a geometric candidate, not evidence of a functional synapse.
"""

import math
import re
from collections import Counter

import numpy as np

from service.infrastructure.connectome.cable_spatial_index import CableSpatialIndex
from service.infrastructure.connectome.neighbors import outgoing


def source_geometry_diagnostics(cell, graph, index, *, threshold_mv, duration_ms,
                                simulation_sha256, max_distance_um):
    """Map every registered outgoing graph synapse without using simulated traces."""
    try:
        body = cell['id']
        source_hash = cell['morphology_sha256']
        geometry = cell['geometry']
        graph_hash = graph.provenance['manifest_sha256']
        ids_hash = graph.provenance['array_sha256']['ids.npy']
        source_md5 = index.manifest['source_md5']
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Missing source geometry identity') from exc
    if (type(body) is not int or body <= 0
            or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                   for value in (source_hash, graph_hash, ids_hash, simulation_sha256))
            or not isinstance(source_md5, str) or not re.fullmatch('[a-f0-9]{32}', source_md5)
            or index.manifest.get('ids_sha256') != ids_hash
            or type(duration_ms) is not int or duration_ms < 1
            or type(threshold_mv) not in (int, float) or not math.isfinite(threshold_mv)
            or type(max_distance_um) not in (int, float)
            or not math.isfinite(max_distance_um) or max_distance_um < 0):
        raise ValueError('Invalid source geometry identity')
    ids = np.asarray(geometry.get('edge_node_ids'))
    starts = np.asarray(geometry.get('starts_um'), dtype=float)
    ends = np.asarray(geometry.get('ends_um'), dtype=float)
    radii = np.asarray(geometry.get('endpoint_radii_um'), dtype=float)
    if (ids.ndim != 1 or ids.dtype.kind not in 'iu' or len(ids) == 0
            or len(np.unique(ids)) != len(ids) or np.any(ids <= 0)
            or starts.shape != (len(ids), 3) or ends.shape != starts.shape
            or radii.shape != (len(ids), 2) or not np.isfinite(starts).all()
            or not np.isfinite(ends).all() or not np.isfinite(radii).all()
            or np.any(radii <= 0)):
        raise ValueError('Invalid source cable geometry')
    vector = ends - starts
    length2 = np.einsum('ij,ij->i', vector, vector)
    if not np.isfinite(length2).all() or np.any(length2 <= 0):
        raise ValueError('Invalid source cable length')
    edges = outgoing(graph, body, 0, len(graph.posts))
    if edges['next_offset'] is not None:
        raise ValueError('Incomplete outgoing graph scan')
    expected = {int(row['target_id']): row['synapse_count'] for row in edges['items']}
    if len(expected) != len(edges['items']):
        raise ValueError('Ambiguous outgoing graph edges')
    page = index.query(body, 'outgoing', limit=None)
    if (page.get('source_md5') != source_md5 or page.get('truncated')
            or page.get('returned') != page.get('total')
            or len(page.get('pairs', [])) != page.get('total')):
        raise ValueError('Incomplete source synapse scan')
    pairs = [pair for pair in page['pairs'] if pair.get('body_post') in expected]
    if Counter(pair['body_post'] for pair in pairs) != Counter(expected):
        raise ValueError('Source synapse counts do not match graph')
    if any(pair.get('body_pre') != body or any(
            type(pair.get(f'{axis}_pre')) is not int or pair[f'{axis}_pre'] < 0
            for axis in 'xyz') for pair in pairs):
        raise ValueError('Invalid source synapse coordinates')
    order = np.argsort(ids)
    prepared = (ids[order].astype(int).tolist(), starts[order], radii[order],
                vector[order], length2[order])
    points = np.asarray([[pair[f'{axis}_pre'] * .008 for axis in 'xyz']
                         for pair in pairs], dtype=float).reshape(-1, 3)
    mapped = CableSpatialIndex(prepared).query(points) if pairs else {
        'child_node_ids': [], 'segment_fractions': [], 'centerline_distances_um': []}
    positions = {int(child): position for position, child in enumerate(ids)}
    candidates = []
    for pair, child, fraction, distance in zip(pairs, mapped['child_node_ids'],
            mapped['segment_fractions'], mapped['centerline_distances_um'], strict=True):
        unresolved = distance > max_distance_um
        candidates.append({'included_in_graph': True, 'partner_id': str(pair['body_post']),
            'source_position_8nm': [pair[f'{axis}_pre'] for axis in 'xyz'],
            'child_node_id': child, 'segment_fraction': fraction,
            'centerline_distance_um': distance, 'result_segment_index': positions[child],
            'status': 'geometry_unresolved' if unresolved else 'timing_or_trace_ambiguous',
            'stimulated_ticks_ms': None, 'control_ticks_ms': None})
    return {'body_id': str(body), 'morphology_sha256': source_hash,
            'source_md5': source_md5, 'graph_sha256': graph_hash,
            'simulation_sha256': simulation_sha256, 'duration_ms': duration_ms,
            'threshold_mv': float(threshold_mv), 'source_pairs': len(candidates),
            'graph_pairs': len(candidates), 'candidates': candidates,
            'interpretation': 'unobserved nearest-cable candidates; no activity inferred'}
