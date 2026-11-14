"""Build explicit physical-input schedules from population graph feedback.

Signs and conductances are assumptions supplied by the caller. This creates
candidate inputs only; it does not run a closed-loop solver.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from contextlib import closing

from service.infrastructure.stimulation.population.pair_mapping import (
    match_fragment_inputs_batch,
    schedule_matched_fragment_events,
)


def schedule_verified_source_batch(batch, source_ids, graph, index, directories, parameters, *,
                                   duration_ms, max_events, max_source_distance_um,
                                   max_target_distance_um, target_provider=None, pair_cache=None,
                                   include_control_crossings=False):
    """Map one provisional physical-output batch to an experimental replay schedule.

    The producer must exhaust and verify the complete source stream before any
    output is published; graph and original diagnostics must be authenticated.
    """
    if (not isinstance(batch, dict) or set(batch) != {'diagnostics', 'events'}
            or not isinstance(batch['diagnostics'], dict)
            or not isinstance(batch['events'], list)):
        raise ValueError('Invalid verified source batch')
    pairs = sorted({(event['source_id'], event['target_id']) for event in batch['events']})
    if any(source not in batch['diagnostics'] for source, _ in pairs):
        raise ValueError('Missing verified source diagnostics')
    control_options = {'include_control_crossings': True} if include_control_crossings else {}
    mappings = match_fragment_inputs_batch(pairs, batch['diagnostics'], index, graph,
        directories, max_source_distance_um=max_source_distance_um,
        max_target_distance_um=max_target_distance_um, duration_ms=duration_ms,
        _target_provider=target_provider, _pair_cache=pair_cache, **control_options)
    return population_feedback_schedule(source_ids, {'graph_sha256':
        graph.provenance['manifest_sha256'], 'delivery_delay_ms': 2,
        'events': batch['events']}, mappings, parameters, duration_ms=duration_ms,
        max_events=max_events, output_targets=sorted({target for _, target in pairs}))


def combine_partial_feedback_schedules(source_ids, graph_sha256, schedules, *, max_events):
    """Combine provisional target batches; caller must verify the source stream to its end."""
    if (not isinstance(source_ids, list) or not source_ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids) or type(max_events) is not int
            or max_events < 1 or not isinstance(graph_sha256, str)
            or len(graph_sha256) != 64
            or any(c not in '0123456789abcdef' for c in graph_sha256)):
        raise ValueError('Invalid combined feedback identity')
    events = {body: [] for body in source_ids}
    provenance = {body: [] for body in source_ids}
    hashes, unresolved = {}, []
    total = outside = 0
    for schedule in schedules:
        if (not isinstance(schedule, dict) or schedule.get('graph_sha256') != graph_sha256
                or schedule.get('source_ids') != source_ids
                or not isinstance(schedule.get('partial_target_ids'), list)
                or not isinstance(schedule.get('events_by_target'), dict)
                or not isinstance(schedule.get('provenance_by_target'), dict)
                or not isinstance(schedule.get('target_morphology_sha256'), dict)
                or not isinstance(schedule.get('unresolved'), list)
                or type(schedule.get('outside_window')) is not int
                or schedule['outside_window'] < 0):
            raise ValueError('Invalid partial feedback schedule')
        targets = schedule['partial_target_ids']
        if (len(set(targets)) != len(targets) or not set(targets).issubset(events)
                or set(schedule['events_by_target']) != set(targets)
                or set(schedule['provenance_by_target']) != set(targets)
                or not set(schedule['target_morphology_sha256']).issubset(targets)):
            raise ValueError('Invalid partial feedback targets')
        evidence = schedule['provenance_by_target']
        checksum = hashlib.sha256(json.dumps({str(body): rows for body, rows in evidence.items()},
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if checksum != schedule.get('provenance_sha256'):
            raise ValueError('Partial feedback provenance mismatch')
        count = 0
        for body in targets:
            current, proof = schedule['events_by_target'][body], evidence[body]
            if (not isinstance(current, list) or not isinstance(proof, list)
                    or len(current) != len(proof)):
                raise ValueError('Invalid partial feedback events')
            events[body].extend(current)
            provenance[body].extend(proof)
            count += len(current)
        if type(schedule.get('event_count')) is not int or schedule['event_count'] != count:
            raise ValueError('Partial feedback event count mismatch')
        total += count
        if total > max_events:
            raise ValueError('Combined feedback exceeds event limit')
        for body, digest in schedule['target_morphology_sha256'].items():
            if body in hashes and hashes[body] != digest:
                raise ValueError('Inconsistent target morphology')
            hashes[body] = digest
        unresolved.extend(schedule['unresolved'])
        outside += schedule['outside_window']
    # GPU batches can finish in different orders. Canonicalise paired values
    # without losing multiplicity or detaching an event from its provenance.
    for body in source_ids:
        # Empty and singleton lists already have canonical order; retain them
        # without allocating two replacement lists for every inactive neuron.
        if len(events[body]) < 2:
            continue
        pairs = list(zip(events[body], provenance[body], strict=True))
        pairs.sort(key=lambda pair: json.dumps(pair, sort_keys=True, separators=(',', ':'),
                                               allow_nan=False))
        events[body] = [event for event, _ in pairs]
        provenance[body] = [proof for _, proof in pairs]
    unresolved.sort(key=lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'),
                                                  allow_nan=False))
    digest = hashlib.sha256(json.dumps({str(body): rows for body, rows in provenance.items()},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'graph_sha256': graph_sha256, 'source_ids': source_ids.copy(),
        'target_morphology_sha256': hashes, 'events_by_target': events,
        'provenance_by_target': provenance, 'provenance_sha256': digest,
        'event_count': total, 'outside_window': outside, 'unresolved': unresolved,
        'interpretation': 'candidate feedback schedules, explicit uncalibrated kinetics; '
                          'no closed-loop calculation'}


def build_feedback_schedule_from_archives(graph, source_ids, index, directories, parameters, *,
                                          active_path, active_sha256, control_path,
                                          control_sha256, diagnostics_factory,
                                          morphology_sha256, duration_ms, max_events,
                                          max_source_distance_um, max_target_distance_um,
                                          target_provider=None, pair_cache=None,
                                          check_cancelled=None, include_control_crossings=False):
    """Build a provisional fixed schedule after consuming both authenticated archives.

    The caller must independently verify paired run configurations, source
    diagnostics and morphology identities. No convergence is implied.
    """
    from .direct_events import iter_verified_source_feedback
    from .event_archive import iter_aligned_archive_batches
    from .fixed_inputs import fixed_input_digest

    graph_sha256 = graph.provenance['manifest_sha256']
    batches = iter_verified_source_feedback(graph, source_ids,
        iter_aligned_archive_batches(active_path, active_sha256, control_path, control_sha256,
                                     check_cancelled=check_cancelled),
        duration_ms=duration_ms, paired_batches=True,
        diagnostics_factory=diagnostics_factory, morphology_sha256=morphology_sha256,
    )
    def checked_schedules():
        with closing(batches):
            for batch in batches:
                # Silence is not evidence that unmapped synapses were quiet.
                for diagnostic in batch['diagnostics'].values():
                    for candidate in diagnostic['candidates']:
                        if (candidate.get('included_in_graph') is True
                                and candidate.get('status') == 'geometry_unresolved'):
                            raise ValueError('Unresolved source geometry prevents complete '
                                             'feedback')
                if batch['events']:
                    control_options = ({'include_control_crossings': True}
                                       if include_control_crossings else {})
                    yield schedule_verified_source_batch(batch, source_ids, graph, index,
                        directories, parameters, duration_ms=duration_ms, max_events=max_events,
                        max_source_distance_um=max_source_distance_um,
                        max_target_distance_um=max_target_distance_um,
                        target_provider=target_provider, pair_cache=pair_cache, **control_options)

    partial = checked_schedules()
    try:
        schedule = combine_partial_feedback_schedules(source_ids, graph_sha256, partial,
                                                       max_events=max_events)
    finally:
        partial.close()
    if any(morphology_sha256.get(body) != digest for body, digest
           in schedule['target_morphology_sha256'].items()):
        raise ValueError('Feedback target morphology digest mismatch')
    return {'schedule': schedule, 'schedule_sha256': fixed_input_digest(schedule),
            'active_archive_sha256': active_sha256, 'control_archive_sha256': control_sha256,
            'interpretation': 'provisional fixed schedule; paired run identity must be verified'}


def population_feedback_schedule(source_ids, feedback, mappings, parameters, *, duration_ms,
                                 max_events, allow_partial_geometry=False, output_targets=None):
    if (not isinstance(source_ids, list) or not source_ids
            or any(type(body) is not int or body <= 0 for body in source_ids)
            or len(set(source_ids)) != len(source_ids)
            or not isinstance(feedback, dict) or not isinstance(feedback.get('events'), list)
            or feedback.get('delivery_delay_ms') != 2
            or not isinstance(mappings, list) or not isinstance(parameters, dict)
            or type(allow_partial_geometry) is not bool
            or type(duration_ms) is not int or duration_ms < 1
            or type(max_events) is not int or max_events < 1):
        raise ValueError('Invalid population feedback inputs')
    selected = set(source_ids)
    if output_targets is not None and (
            not isinstance(output_targets, list) or len(set(output_targets)) != len(output_targets)
            or any(type(body) is not int or body not in selected for body in output_targets)):
        raise ValueError('Invalid feedback output targets')
    targets = source_ids if output_targets is None else output_targets
    target_set = selected if output_targets is None else set(targets)
    graph_hash = feedback.get('graph_sha256')
    if (not isinstance(graph_hash, str) or len(graph_hash) != 64
            or any(char not in '0123456789abcdef' for char in graph_hash)):
        raise ValueError('Feedback graph identity mismatch')
    by_pair = {}
    target_hashes = {}
    for mapping in mappings:
        if (not isinstance(mapping, dict)
                or ('unresolved_target_geometry' in mapping and not allow_partial_geometry)
                or ('unresolved_source_geometry' in mapping and not allow_partial_geometry)
                or mapping.get('target_id') not in target_set
                or type(mapping.get('source_id')) is not int or mapping['source_id'] <= 0):
            raise ValueError('Incomplete or invalid feedback mapping')
        kind = mapping.get('input_kind', 'physical-source-edge')
        if (kind not in ('physical-source-edge', 'lif-network-spike')
                or (kind == 'physical-source-edge') != (mapping['source_id'] in selected)):
            raise ValueError('Feedback mapping source type mismatch')
        pair = (mapping['source_id'], mapping['target_id'])
        if pair in by_pair:
            raise ValueError('Duplicate feedback mapping')
        sha = mapping.get('target_morphology_sha256')
        if (not isinstance(sha, str) or len(sha) != 64
                or any(char not in '0123456789abcdef' for char in sha)):
            raise ValueError('Invalid target morphology identity')
        if mapping['target_id'] in target_hashes and target_hashes[mapping['target_id']] != sha:
            raise ValueError('Inconsistent target morphology')
        target_hashes[mapping['target_id']] = sha
        current_graph = mapping.get('graph_sha256')
        if (not isinstance(current_graph, str) or len(current_graph) != 64
                or any(char not in '0123456789abcdef' for char in current_graph)
                or current_graph != graph_hash):
            raise ValueError('Inconsistent graph identity')
        graph_hash = current_graph
        by_pair[pair] = mapping
    grouped = {}
    for item in feedback['events']:
        if (not isinstance(item, dict)
                or item.get('kind') not in ('physical-source-edge', 'lif-network-spike')
                or type(item.get('source_id')) is not int or item['source_id'] <= 0
                or (item['kind'] == 'physical-source-edge') != (item['source_id'] in selected)
                or item.get('target_id') not in selected
                or type(item.get('emission_tick_ms')) is not int
                or not 1 <= item['emission_tick_ms'] <= duration_ms
                or type(item.get('synapse_count')) is not int or item['synapse_count'] <= 0
                or type(item.get('predicted_sign')) is not int
                or item.get('delivery_tick_ms') != item['emission_tick_ms'] + 2
                or item.get('within_window') is not (item['delivery_tick_ms'] <= duration_ms)
                or item.get('affects_replay', item['delivery_tick_ms'] < duration_ms)
                   is not (item['delivery_tick_ms'] < duration_ms)):
            raise ValueError('Invalid or unsupported feedback event')
        pair = (item['source_id'], item['target_id'])
        if (pair not in by_pair
                or by_pair[pair].get('input_kind', 'physical-source-edge') != item['kind']):
            raise ValueError('Feedback event source type mismatch')
        grouped.setdefault(pair, []).append(item)
    if set(grouped) != set(by_pair):
        raise ValueError('Feedback mappings do not cover the observed edges')
    result = {body: [] for body in targets}
    provenance = {body: [] for body in targets}
    total = outside = 0
    unresolved = []
    for pair, items in grouped.items():
        signs = {item['predicted_sign'] for item in items}
        if len(signs) != 1 or next(iter(signs)) not in parameters:
            raise ValueError('Missing explicit parameters for predicted sign')
        settings = parameters[next(iter(signs))]
        if not isinstance(settings, dict) or set(settings) != {
            'weight_us', 'tau1_ms', 'tau2_ms', 'reversal_mv'
        }:
            raise ValueError('Invalid feedback parameters')
        expected = Counter()
        for item in items:
            expected[item['emission_tick_ms']] += item['synapse_count']
        candidates = by_pair[pair].get('candidates')
        if not isinstance(candidates, list):
            raise ValueError('Invalid mapped candidates')
        missing = by_pair[pair].get('unresolved_target_geometry', [])
        source_missing = by_pair[pair].get('unresolved_source_geometry', [])
        if (not isinstance(source_missing, list)
                or any(not isinstance(row, dict)
                       or set(row) != {'source_position_8nm', 'target_position_8nm',
                                       'source_distance_um'}
                       or any(not isinstance(row[key], list) or len(row[key]) != 3
                              or any(type(v) is not int or v < 0 for v in row[key])
                              for key in ('source_position_8nm', 'target_position_8nm'))
                       or type(row['source_distance_um']) not in (int, float)
                       or not math.isfinite(row['source_distance_um'])
                       or row['source_distance_um'] < 0 for row in source_missing)):
            raise ValueError('Invalid unresolved source candidates')
        if not isinstance(missing, list):
            raise ValueError('Invalid unresolved candidates')
        for candidate in missing:
            if (not isinstance(candidate, dict)
                    or not isinstance(candidate.get('stimulated_ticks_ms'), list)
                    or any(type(tick) is not int or not 1 <= tick <= duration_ms
                           for tick in candidate['stimulated_ticks_ms'])
                    or len(set(candidate['stimulated_ticks_ms']))
                       != len(candidate['stimulated_ticks_ms'])):
                raise ValueError('Invalid unresolved candidate')
            unresolved.append({'source_id': pair[0], 'target_id': pair[1], **candidate})
        observed = Counter(tick for candidate in candidates
                           for tick in candidate.get('stimulated_ticks_ms', []))
        observed.update(tick for candidate in missing for tick in candidate['stimulated_ticks_ms'])
        if observed != expected:
            raise ValueError('Mapped events do not match graph feedback')
        complete_only = {key: value for key, value in by_pair[pair].items()
                         if key not in ('unresolved_target_geometry', 'unresolved_source_geometry')}
        scheduled = schedule_matched_fragment_events(
            complete_only, delay_ms=2, duration_ms=duration_ms,
            max_events=max_events - total if total < max_events else 1, **settings)
        total += len(scheduled['events'])
        if total > max_events:
            raise ValueError('Population feedback exceeds event limit')
        outside += scheduled['outside_window']
        result[pair[1]].extend(scheduled['events'])
        provenance[pair[1]].extend({'source_id': pair[0], **item} for item in scheduled['evidence'])
    provenance_digest = hashlib.sha256(json.dumps(
        {str(body): rows for body, rows in provenance.items()}, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    output = {'graph_sha256': graph_hash, 'source_ids': source_ids.copy(),
            'target_morphology_sha256': target_hashes,
            'events_by_target': result, 'provenance_by_target': provenance,
            'provenance_sha256': provenance_digest,
            'event_count': total, 'outside_window': outside, 'unresolved': unresolved,
            'interpretation': 'candidate feedback schedules, explicit uncalibrated kinetics; '
                              'no closed-loop calculation'}
    if output_targets is not None:
        output['partial_target_ids'] = output_targets.copy()
    return output
