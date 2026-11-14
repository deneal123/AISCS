"""Prepare verified feedback geometry for an explicitly bounded cable replay.

This module does not choose limits or enable approximations in the production
executor. Geometry alone cannot establish numerical or biological validity.
"""

from __future__ import annotations

import copy

from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.feedback.endpoint_discretization import (
    apply_shared_grid,
    merge_shared_grid_requirements,
    prepare_discretized_events,
    prepare_shared_discretization,
)
from service.infrastructure.stimulation.feedback.observation_audit import (
    audit_feedback_observations,
)


def prepare_feedback_discretization(schedule, index, directories, *, expected_source_md5,
                                    max_shift_um, max_observation_distance_um, max_nseg,
                                    _pair_cache=None):
    """Verify source geometry and prepare each target without mutating the schedule."""
    cache_options = {'_pair_cache': _pair_cache} if _pair_cache is not None else {}
    proof = audit_feedback_observations(schedule, index, directories,
                                        expected_source_md5=expected_source_md5, **cache_options)
    prepared = {}
    for body, events in schedule['events_by_target'].items():
        if not events:
            continue
        origins = schedule['provenance_by_target'][body]
        if any('source_position_8nm' not in row for row in origins):
            raise ValueError('Both source and target observations are required')
        source = read_skeleton(body, directories,
                               expected_sha256=schedule['target_morphology_sha256'][body])
        nodes = {}
        for line in source['swc'].splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            row = line.split()
            nodes[int(row[0])] = ([float(value) * .008 for value in row[2:5]], int(row[6]))
        edges = {child: [nodes[parent][0], point]
                 for child, (point, parent) in nodes.items() if parent != -1}
        observations = [[value * .008 for value in origin['target_position_8nm']]
                        for origin in origins]
        prepared[body] = prepare_discretized_events(
            events, edges, observations, max_shift_um=max_shift_um,
            max_observation_distance_um=max_observation_distance_um, max_nseg=max_nseg)
    return {'targets': prepared, 'observation_audit': proof,
            'interpretation': 'verified indexed positions and bounded approximation; '
                              'not a validated full-network physical calculation'}


def verify_feedback_discretization(schedule, receipt, index, directories, *, policy):
    """Rebuild a receipt from trusted inputs and externally chosen limits.

    A receipt or its checksum alone does not establish which synapses, source
    data, morphology, or policy the calculation actually used.
    """
    if (not isinstance(policy, dict) or set(policy) != {
            'expected_source_md5', 'max_shift_um', 'max_observation_distance_um', 'max_nseg'}
            or not isinstance(receipt, dict)):
        raise ValueError('Explicit verification policy and receipt required')
    rebuilt = prepare_feedback_discretization(schedule, index, directories, **policy)
    if receipt != rebuilt:
        raise ValueError('Feedback discretization receipt does not match verified inputs')
    return rebuilt


def prepare_shared_feedback_discretization(conditions, index, directories, *, expected_source_md5,
                                           max_shift_um, max_observation_distance_um, max_nseg,
                                           previous_grids=None, uniform=False, _pair_cache=None):
    """Authenticate paired schedules and prepare identical target grids.

    Each value is a (schedule, trusted digest) tuple. This checks source data
    and morphology, but neither selects policy limits nor proves convergence.
    """
    from service.application.feedback.fixed_inputs import fixed_input_digest

    if (type(uniform) is not bool or not isinstance(conditions, dict)
            or set(conditions) != {'control', 'stimulated'}
            or any(not isinstance(value, tuple) or len(value) != 2
                   for value in conditions.values())):
        raise ValueError('Invalid paired discretization schedules')
    schedules, audits, identities = {}, {}, {}
    for name, (schedule, digest) in conditions.items():
        if (not isinstance(schedule, dict) or fixed_input_digest(schedule) != digest
                or not isinstance(schedule.get('events_by_target'), dict)
                or not isinstance(schedule.get('provenance_by_target'), dict)
                or not isinstance(schedule.get('target_morphology_sha256'), dict)):
            raise ValueError('Invalid paired schedule identity')
        cache_options = {'_pair_cache': _pair_cache} if _pair_cache is not None else {}
        audits[name] = audit_feedback_observations(schedule, index, directories,
            expected_source_md5=expected_source_md5, **cache_options)
        schedules[name] = schedule
        for body, body_hash in schedule['target_morphology_sha256'].items():
            if body in identities and identities[body] != body_hash:
                raise ValueError('Paired target morphology mismatch')
            identities[body] = body_hash
    if (schedules['control'].get('graph_sha256') != schedules['stimulated'].get('graph_sha256')
            or not isinstance(schedules['control'].get('source_ids'), list)
            or schedules['control']['source_ids'] != schedules['stimulated'].get('source_ids')):
        raise ValueError('Paired graph mismatch')
    if previous_grids is None:
        previous_grids = {}
    if (not isinstance(previous_grids, dict) or not set(previous_grids).issubset(identities)):
        raise ValueError('Previous grids require authenticated target morphology')
    targets, restart = {}, False
    for body, body_hash in identities.items():
        event_sets = {}
        for name, schedule in schedules.items():
            events = schedule['events_by_target'].get(body, [])
            origins = schedule['provenance_by_target'].get(body, [])
            if (len(events) != len(origins)
                    or any('source_position_8nm' not in row for row in origins)):
                raise ValueError('Both source and target observations are required')
            event_sets[name] = {'events': events, 'observations_um': [
                [value * .008 for value in row['target_position_8nm']] for row in origins]}
        source = read_skeleton(body, directories, expected_sha256=body_hash)
        if source.get('body_id') != str(body) or source.get('sha256') != body_hash:
            raise ValueError('Paired target morphology mismatch')
        nodes = {}
        for line in source['swc'].splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            row = line.split()
            nodes[int(row[0])] = ([float(value) * .008 for value in row[2:5]], int(row[6]))
        edges = {child: [nodes[parent][0], point]
                 for child, (point, parent) in nodes.items() if parent != -1}
        candidate = prepare_shared_discretization(event_sets, edges, max_shift_um=max_shift_um,
            max_observation_distance_um=max_observation_distance_um, max_nseg=max_nseg)
        plan = merge_shared_grid_requirements(previous_grids.get(body, {}),
            candidate['shared']['nseg_by_edge'], max_nseg=max_nseg)
        if uniform:
            # The fast CUDA preparation supports one nseg for the entire cell.
            # Re-audit every event on that exact grid; raising the segment count
            # alone does not guarantee a better location for interior events.
            count = max(plan['nseg_by_edge'].values(), default=1)
            all_edges = {str(child): count for child in edges} if count > 1 else {}
            plan = {'nseg_by_edge': all_edges,
                    'restart_required': all_edges != previous_grids.get(body, {}),
                    'requires_observation_reaudit': True}
        fixed = apply_shared_grid(event_sets, edges, plan['nseg_by_edge'],
            max_shift_um=max_shift_um, max_observation_distance_um=max_observation_distance_um,
            max_nseg=max_nseg)
        targets[body] = {'candidate': candidate, 'plan': plan, 'fixed': fixed}
        restart = restart or plan['restart_required']
    return {'targets': targets, 'observation_audits': audits, 'restart_required': restart,
            'interpretation': 'authenticated observations and shared geometric grids; '
                              'not numerical or biological validation'}


def prepare_uniform_feedback_replays(conditions, index, directories, **policy):
    """Build paired GPU schedules from re-audited uniform target grids.

    Original schedules and their digests remain in the receipt. A grid change
    invalidates earlier traces for both conditions; the caller must restart both.
    """
    from service.application.feedback.fixed_inputs import fixed_input_digest

    if 'uniform' in policy:
        raise ValueError('Uniform grid policy is fixed for GPU replay')
    audit = prepare_shared_feedback_discretization(conditions, index, directories,
                                                    uniform=True, **policy)
    output, counts = {}, {}
    for body, target in audit['targets'].items():
        values = set(target['fixed']['nseg_by_edge'].values())
        if len(values) > 1:
            raise ValueError('Population replay requires uniform cell grid')
        counts[body] = next(iter(values), 1)
    for name, (schedule, original_digest) in conditions.items():
        replay = copy.deepcopy(schedule)
        for body, target in audit['targets'].items():
            if body in replay['events_by_target']:
                replay['events_by_target'][body] = copy.deepcopy(
                    target['fixed']['conditions'][name]['effective_events'])
        output[name] = {'schedule': replay, 'sha256': fixed_input_digest(replay),
                        'original_sha256': original_digest}
    return {'conditions': output, 'nseg_by_body': counts, 'audit': audit,
            'restart_required': audit['restart_required'],
            'interpretation': 'geometry-audited replay inputs; not validated dynamics'}
