"""Recheck saved candidate observations against indexed synapses and SWC geometry.

This is a geometric consistency check, not evidence of physiological transmission.
"""

import math
from collections import Counter, defaultdict

from service.infrastructure.connectome.fragment_mapping import map_fragment_candidates
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.connectome.pair_cache import VerifiedSynapsePairs
from service.infrastructure.connectome.synapse_index import (
    PairQueryLimitExceeded,
    SynapseBatchIndex,
)


def audit_feedback_observations(schedule, index, directories, *, expected_source_md5,
                                _pair_cache=None):
    """Verify event observations without changing their positions or solver settings."""
    if _pair_cache is not None and not isinstance(_pair_cache, VerifiedSynapsePairs):
        raise ValueError('Invalid verified pair cache')
    events = schedule['events_by_target']
    provenance = schedule['provenance_by_target']
    if set(events) != set(provenance):
        raise ValueError('Observation target mismatch')
    groups = defaultdict(list)
    for target, rows in events.items():
        origins = provenance[target]
        if len(rows) != len(origins):
            raise ValueError('Observation event count mismatch')
        for event, origin in zip(rows, origins, strict=True):
            point = origin.get('target_position_8nm')
            source_point = origin.get('source_position_8nm')
            if (type(target) is not int or target <= 0
                    or type(origin.get('source_id')) is not int or origin['source_id'] <= 0
                    or type(origin.get('source_tick_ms')) is not int
                    or not isinstance(point, list) or len(point) != 3
                    or any(type(value) is not int or value < 0 for value in point)
                    or ('source_position_8nm' in origin and (
                        not isinstance(source_point, list) or len(source_point) != 3
                        or any(type(value) is not int or value < 0 for value in source_point)))):
                raise ValueError('Missing registered observation')
            groups[(origin['source_id'], target)].append((event, origin))
    # Query each target in batches of at most twenty source IDs, matching the
    # index contract. This avoids rescanning the same Feather batches per pair.
    sources_by_target = defaultdict(set)
    for source, target in groups:
        sources_by_target[target].add(source)
    indexed_pairs = defaultdict(list)
    if _pair_cache is not None:
        _pair_cache.verify(index, expected_source_md5)
    missing = []
    for target, sources in sources_by_target.items():
        for source in sorted(sources):
            cached = _pair_cache.get(source, target) if _pair_cache is not None else None
            if cached is None:
                missing.append((source, target))
            else:
                indexed_pairs[(source, target)].extend(cached)
    if isinstance(index, SynapseBatchIndex) and missing:
        if index.manifest.get('source_md5') != expected_source_md5:
            raise ValueError('Incomplete or incompatible indexed observations')
        fallback = []
        for start in range(0, len(missing), 128):
            chunk = missing[start:start + 128]
            try:
                exact = index.query_exact_pairs(chunk)
            except PairQueryLimitExceeded:
                fallback.extend(chunk)
            else:
                for pair in chunk:
                    indexed_pairs[pair].extend(exact[pair])
        missing = fallback
    missing_by_target = defaultdict(list)
    for source, target in missing:
        missing_by_target[target].append(source)
    for target, ordered in missing_by_target.items():
        for start in range(0, len(ordered), 20):
            partners = ordered[start:start + 20]
            page = index.query(target, 'incoming', limit=None, partner_ids=partners)
            if (page['truncated'] or page['source_md5'] != expected_source_md5
                    or page['total'] != page['returned'] or page['returned'] != len(page['pairs'])):
                raise ValueError('Incomplete or incompatible indexed observations')
            for pair in page['pairs']:
                source = pair['body_pre']
                if source not in partners or pair['body_post'] != target:
                    raise ValueError('Indexed observation pair mismatch')
                indexed_pairs[(source, target)].append(pair)
    checked = 0
    rows_by_target = defaultdict(list)
    for (source, target), rows in groups.items():
        registered, registered_pairs = Counter(), Counter()
        for pair in indexed_pairs[(source, target)]:
            registered[tuple(pair[f'{axis}_post'] for axis in 'xyz')] += 1
            if all(f'{axis}_pre' in pair for axis in 'xyz'):
                registered_pairs[(tuple(pair[f'{axis}_pre'] for axis in 'xyz'),
                                  tuple(pair[f'{axis}_post'] for axis in 'xyz'))] += 1
        seen, seen_pairs = defaultdict(Counter), defaultdict(Counter)
        for _, origin in rows:
            seen[origin['source_tick_ms']][tuple(origin['target_position_8nm'])] += 1
            if 'source_position_8nm' in origin:
                seen_pairs[origin['source_tick_ms']][
                    (tuple(origin['source_position_8nm']),
                     tuple(origin['target_position_8nm']))] += 1
        if any(count > registered[point] for per_tick in seen.values()
               for point, count in per_tick.items()):
            raise ValueError('Event observation absent from indexed synapses')
        if any(count > registered_pairs[pair] for per_tick in seen_pairs.values()
               for pair, count in per_tick.items()):
            raise ValueError('Event source-target observation absent from indexed synapses')
        rows_by_target[target].extend(rows)
    # Preserve pair-level index checks above, then project each target's points
    # together so that its verified SWC is parsed only once for this audit.
    for target, rows in rows_by_target.items():
        expected_hash = schedule['target_morphology_sha256'][target]
        skeleton = read_skeleton(target, directories, expected_sha256=expected_hash)
        if skeleton['body_id'] != str(target) or skeleton['sha256'] != expected_hash:
            raise ValueError('Observation morphology mismatch')
        points = [[value * .008 for value in origin['target_position_8nm']]
                  for _, origin in rows]
        mapped = map_fragment_candidates(skeleton['swc'], points)
        for (event, origin), child, fraction, distance in zip(
                rows, mapped['child_node_ids'], mapped['segment_fractions'],
                mapped['centerline_distances_um'], strict=True):
            original_distance = origin.get('target_distance_um')
            if (type(original_distance) not in (int, float) or not math.isfinite(original_distance)
                    or child != event['child_node_id']
                    or not math.isclose(fraction, event['position'], rel_tol=0, abs_tol=1e-10)
                    or not math.isclose(distance, original_distance, rel_tol=0, abs_tol=1e-9)):
                raise ValueError('Observation projection mismatch')
            checked += 1
    if _pair_cache is not None:
        _pair_cache.verify(index, expected_source_md5)
    return {'verified_events': checked, 'verified_pairs': len(groups),
            'source_md5': expected_source_md5,
            'interpretation': 'indexed observation and geometry only; not physiological validation'}
