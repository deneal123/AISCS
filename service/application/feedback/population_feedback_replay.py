"""One physical population replay with explicitly supplied candidate feedback.

This is one iteration against a fixed graph schedule, not a closed-loop solver.
"""

from __future__ import annotations

import math
import re

from service.application.feedback.cell_solution_cache import CellSolutionCache
from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.feedback_discretization import (
    prepare_feedback_discretization,
)
from service.infrastructure.stimulation.network_recording import record_independent_cells
from service.infrastructure.stimulation.swc_reference import simulate_registered_swc_reference


def replay_population_feedback(config, directories, schedule, morphology_hashes, *,
                               omitted_pairs, provenance_sink=None, solution_sink=None,
                               discretization_policy=None, synapse_index=None,
                               cell_progress=None, cell_cache=None):
    if not isinstance(config, FragmentPopulationConfig):
        raise ValueError('Validated population configuration required')
    if cell_progress is not None and not callable(cell_progress):
        raise ValueError('Invalid cell progress callback')
    if cell_cache is not None and not isinstance(cell_cache, CellSolutionCache):
        raise ValueError('Invalid run-local cell cache')
    ids = config.source_ids
    if (not isinstance(schedule, dict)
            or schedule.get('graph_sha256') != config.graph_manifest_sha256
            or schedule.get('source_ids') != ids
            or not isinstance(schedule.get('events_by_target'), dict)
            or set(schedule['events_by_target']) != set(ids)
            or not isinstance(schedule.get('target_morphology_sha256'), dict)
            or not isinstance(morphology_hashes, dict) or set(morphology_hashes) != set(ids)
            or any(not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest)
                   for digest in morphology_hashes.values())
            or not isinstance(omitted_pairs, list)
            or any(not isinstance(pair, tuple) or len(pair) != 2
                   or type(pair[0]) is not int or pair[0] <= 0 or pair[1] not in ids
                   for pair in omitted_pairs)
            or len(set(omitted_pairs)) != len(omitted_pairs)):
        raise ValueError('Incompatible population feedback identity')
    if any(morphology_hashes.get(target) != digest
           for target, digest in schedule['target_morphology_sha256'].items()):
        raise ValueError('Target morphology identity mismatch')
    unresolved = schedule.get('unresolved', [])
    if (not isinstance(unresolved, list)
            or any(not isinstance(item, dict)
                   or (item.get('source_id'), item.get('target_id')) not in omitted_pairs
                   for item in unresolved)):
        raise ValueError('Unreported unresolved feedback')
    events = schedule['events_by_target']
    if (any(not isinstance(events[body], list) for body in ids)
            or sum(len(events[body]) for body in ids) != schedule.get('event_count')):
        raise ValueError('Population event count mismatch')
    settings = config.execution_parameters()
    simulation = settings['simulation_parameters']
    if 'synaptic_events' in simulation:
        raise ValueError('Conflicting synaptic events')
    prepared = None
    if discretization_policy is not None:
        if (not isinstance(discretization_policy, dict) or set(discretization_policy) != {
                'expected_source_md5', 'max_shift_um', 'max_observation_distance_um', 'max_nseg'}
                or synapse_index is None or simulation.get('nseg_per_edge') != 1
                or not isinstance(discretization_policy.get('expected_source_md5'), str)
                or not re.fullmatch(r'[a-f0-9]{32}', discretization_policy['expected_source_md5'])
                or any(type(discretization_policy.get(key)) not in (int, float)
                       or not math.isfinite(discretization_policy[key])
                       or discretization_policy[key] < 0
                       for key in ('max_shift_um', 'max_observation_distance_um'))
                or type(discretization_policy.get('max_nseg')) is not int
                or discretization_policy['max_nseg'] < 1
                or discretization_policy['max_nseg'] % 2 != 1):
            raise ValueError('Explicit verified discretization policy and index required')
        prepared = prepare_feedback_discretization(
            schedule, synapse_index, directories, **discretization_policy)
    elif synapse_index is not None:
        raise ValueError('Discretization index requires explicit policy')
    # Refuse the entire schedule before solving its first cell. Otherwise a
    # late endpoint event could waste a long replay and hide a known numerical
    # problem in already computed partial results.
    if prepared is None and any(
            isinstance(event, dict) and type(event.get('position')) in (int, float)
            and event['position'] in (0, 1) for body in ids for event in events[body]):
        raise ValueError('Synapse at zero-area section endpoint is unsupported')
    def solutions():
        for completed, body in enumerate(ids, 1):
            cell_preparation = prepared['targets'].get(body) if prepared else None
            cell_events = cell_preparation['effective_events'] if cell_preparation else events[body]
            overrides = ({'nseg_by_edge': cell_preparation['nseg_by_edge']}
                         if cell_preparation else {})
            cache_key = (cell_cache.key(body, morphology_hashes[body], simulation, cell_events,
                                        overrides) if cell_cache is not None else None)
            cached = cell_cache.get(cache_key) if cell_cache is not None else None
            if cached is None:
                solution, proof = simulate_registered_swc_reference(
                    body, directories, expected_morphology_sha256=morphology_hashes[body],
                    synaptic_events=cell_events, **simulation, **overrides)
            else:
                solution, proof = cached
                source = read_skeleton(body, directories, expected_sha256=morphology_hashes[body])
                if source['source'] != proof.get('morphology_source'):
                    raise ValueError('Cached morphology provenance mismatch')
            if (str(proof.get('body_id')) != str(body)
                    or proof.get('morphology_sha256') != morphology_hashes[body]):
                raise ValueError('Population morphology identity mismatch')
            if cell_cache is not None and cached is None:
                cell_cache.put(cache_key, (solution, proof), group=body)
            if solution_sink is not None:
                solution_sink(body, solution, proof)
            yield solution, proof
            if cell_progress is not None:
                cell_progress(completed, len(ids))

    recording = record_independent_cells(
        solutions(), settings['electrode_um'], settings['reference_um'],
        source_model=settings['source_model'], provenance_sink=provenance_sink)
    if recording['cells'] != len(ids):
        raise ValueError('Population recording is incomplete')
    return {'source_ids': ids.copy(), 'source_configuration_sha256': config.digest(),
            'feedback_event_count': schedule['event_count'],
            'incomplete_pairs': omitted_pairs.copy(),
            'unresolved_candidates': len(unresolved),
            **({'discretization': prepared} if prepared is not None else {}),
            'recording': recording,
            'interpretation': 'one physical population replay using fixed uncalibrated feedback; '
                              'not closed-loop and not a full-network physical recording'}
