"""One physical population replay with explicitly supplied candidate feedback.

This is one iteration against a fixed graph schedule, not a closed-loop solver.
"""

from __future__ import annotations

import math
import re

from service.application.feedback.cell_cache import CellSolutionCache
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.execution.ordered_pool import LocalResult, ordered_process_map
from service.infrastructure.stimulation.feedback.discretization import (
    prepare_feedback_discretization,
)
from service.infrastructure.stimulation.network_recording import record_independent_cells
from service.infrastructure.stimulation.swc_reference import simulate_registered_swc_reference


def _solve_cell(task):
    body, directories, digest, cell_events, simulation, overrides, cache_key = task
    solution, proof = simulate_registered_swc_reference(
        body, directories, expected_morphology_sha256=digest,
        synaptic_events=cell_events, **simulation, **overrides)
    return body, cache_key, solution, proof, False


def replay_population_feedback(config, directories, schedule, morphology_hashes, *,
                               omitted_pairs, provenance_sink=None, solution_sink=None,
                               discretization_policy=None, synapse_index=None,
                               cell_progress=None, gpu_progress=None, cell_cache=None,
                               gpu_geometry_cache=None,
                               experimental_solver_backend=None, pair_cache=None,
                               experimental_cell_workers=1,
                               experimental_gpu_output_budget_bytes=None,
                               experimental_gpu_allow_table_clamp=False,
                               experimental_gpu_stream_cells=None,
                               experimental_gpu_window_steps=None, windowed_diagnostics=None,
                               windowed_output_sink=None, gpu_packing_cache=None,
                               experimental_gpu_device_reduction=False,
                               experimental_gpu_preparation_workers=1):
    if not isinstance(config, FragmentPopulationConfig):
        raise ValueError('Validated population configuration required')
    if cell_progress is not None and not callable(cell_progress):
        raise ValueError('Invalid cell progress callback')
    if gpu_progress is not None and (not callable(gpu_progress)
                                     or experimental_solver_backend != 'experimental_cuda'):
        raise ValueError('GPU progress requires CUDA replay')
    if cell_cache is not None and not isinstance(cell_cache, CellSolutionCache):
        raise ValueError('Invalid run-local cell cache')
    if gpu_geometry_cache is not None and (not isinstance(gpu_geometry_cache, CellSolutionCache)
                                           or experimental_solver_backend != 'experimental_cuda'):
        raise ValueError('Invalid GPU geometry cache')
    if type(experimental_cell_workers) is not int or not 1 <= experimental_cell_workers <= 8:
        raise ValueError('Invalid experimental cell worker count')
    if experimental_solver_backend not in (None, 'experimental_coreneuron', 'experimental_cuda'):
        raise ValueError('Invalid experimental solver backend')
    if experimental_solver_backend == 'experimental_cuda':
        if (type(experimental_gpu_output_budget_bytes) is not int
                or experimental_gpu_output_budget_bytes < 1 or experimental_cell_workers != 1
                or cell_cache is not None or type(experimental_gpu_allow_table_clamp) is not bool
                or (experimental_gpu_stream_cells is not None
                    and (type(experimental_gpu_stream_cells) is not int
                         or experimental_gpu_stream_cells < 1 or gpu_progress is not None))):
            raise ValueError('CUDA replay requires an explicit output budget and no cell cache')
    elif (experimental_gpu_output_budget_bytes is not None or experimental_gpu_allow_table_clamp
          or experimental_gpu_stream_cells is not None):
        raise ValueError('GPU output budget requires CUDA replay')
    if type(experimental_gpu_device_reduction) is not bool:
        raise ValueError('Invalid GPU reduction option')
    if (type(experimental_gpu_preparation_workers) is not int
            or not 1 <= experimental_gpu_preparation_workers <= 8
            or (experimental_gpu_preparation_workers > 1
                and (experimental_gpu_window_steps is None or gpu_geometry_cache is not None))):
        raise ValueError('Parallel GPU preparation requires uncached windowed CUDA')
    if experimental_gpu_window_steps is not None:
        from service.infrastructure.stimulation.experimental_gpu.packing_cache import (
            PackedTreeCache,
        )

        if (experimental_solver_backend != 'experimental_cuda'
                or type(experimental_gpu_window_steps) is not int
                or experimental_gpu_window_steps < 1 or experimental_gpu_stream_cells is None
                or gpu_progress is not None or solution_sink is not None
                or provenance_sink is not None
                or not isinstance(windowed_diagnostics, dict)
                or (windowed_output_sink is not None and not callable(windowed_output_sink))
                or (gpu_packing_cache is not None
                    and not isinstance(gpu_packing_cache, PackedTreeCache))):
            raise ValueError('Invalid experimental windowed replay options')
    elif (experimental_gpu_device_reduction or any(value is not None for value in
          (windowed_diagnostics, windowed_output_sink, gpu_packing_cache))):
        raise ValueError('Windowed replay options require windowed CUDA')
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
    if experimental_solver_backend == 'experimental_coreneuron':
        simulation = {**simulation, 'field_coupling': 'experimental_virtual_current',
                      'solver_backend': experimental_solver_backend}
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
        cache_options = {'_pair_cache': pair_cache} if pair_cache is not None else {}
        prepared = prepare_feedback_discretization(
            schedule, synapse_index, directories, **discretization_policy, **cache_options)
    elif synapse_index is not None:
        raise ValueError('Discretization index requires explicit policy')
    elif pair_cache is not None:
        raise ValueError('Pair cache requires explicit discretization policy')
    # Refuse the entire schedule before solving its first cell. Otherwise a
    # late endpoint event could waste a long replay and hide a known numerical
    # problem in already computed partial results.
    if prepared is None and any(
            isinstance(event, dict) and type(event.get('position')) in (int, float)
            and event['position'] in (0, 1) for body in ids for event in events[body]):
        raise ValueError('Synapse at zero-area section endpoint is unsupported')
    def tasks():
        for body in ids:
            cell_preparation = prepared['targets'].get(body) if prepared else None
            cell_events = cell_preparation['effective_events'] if cell_preparation else events[body]
            overrides = ({'nseg_by_edge': cell_preparation['nseg_by_edge']}
                         if cell_preparation else {})
            cache_key = (cell_cache.key(body, morphology_hashes[body], simulation, cell_events,
                                        overrides) if cell_cache is not None else None)
            cached = cell_cache.get(cache_key) if cell_cache is not None else None
            if cached is None:
                yield (body, directories, morphology_hashes[body], cell_events,
                       simulation, overrides, cache_key)
            else:
                solution, proof = cached
                source = read_skeleton(body, directories, expected_sha256=morphology_hashes[body])
                if source['source'] != proof.get('morphology_source'):
                    raise ValueError('Cached morphology provenance mismatch')
                yield LocalResult((body, cache_key, solution, proof, True))

    clamped_cell_ids = []

    if experimental_gpu_window_steps is not None:
        from service.application.feedback.windowed_replay import replay_windowed_sources

        if set(windowed_diagnostics) != set(ids) or settings['source_model'] != 'pointsource':
            raise ValueError('Invalid windowed source diagnostics or recording model')
        requests = []
        for body in ids:
            item = prepared['targets'].get(body) if prepared else None
            requests.append({'id': body, 'expected_sha256': morphology_hashes[body],
                'events': item['effective_events'] if item else events[body],
                'nseg_by_edge': ({int(key): value for key, value in item['nseg_by_edge'].items()}
                                 if item else {})})
        windowed = replay_windowed_sources(requests, directories, simulation, windowed_diagnostics,
            electrode_um=settings['electrode_um'], reference_um=settings['reference_um'],
            threshold_mv=config.threshold_mv, duration_ms=int(config.simulation.duration_ms),
            max_source_distance_um=(config.max_distance_um
                                    if config.allow_partial_geometry is True else None),
            max_cells=experimental_gpu_stream_cells,
            output_budget_bytes=experimental_gpu_output_budget_bytes,
            window_steps=experimental_gpu_window_steps,
            allow_table_clamp=experimental_gpu_allow_table_clamp,
            progress=cell_progress, packing_cache=gpu_packing_cache,
            geometry_cache=gpu_geometry_cache, device_reduction=experimental_gpu_device_reduction,
            preparation_workers=experimental_gpu_preparation_workers)
        if list(windowed['sources']) != ids:
            raise ValueError('Incomplete windowed source output')
        if windowed_output_sink is not None:
            for body in ids:
                windowed_output_sink(body, windowed['sources'][body])
        recording = windowed['recording']
        recording.update(cells=len(ids), source_model='pointsource',
                         cell_provenance_fields_present=False,
                         cell_provenance_exported=False)
        return {'source_ids': ids.copy(), 'source_configuration_sha256': config.digest(),
                'feedback_event_count': schedule['event_count'],
                'incomplete_pairs': omitted_pairs.copy(), 'unresolved_candidates': len(unresolved),
                'experimental_solver_backend': experimental_solver_backend,
                'experimental_gpu_table_clamped_cell_ids': windowed['table_clamped_cell_ids'],
                **({'discretization': prepared} if prepared is not None else {}),
                'recording': recording,
                'interpretation': 'experimental windowed source replay; not publishable'}

    def solutions():
        if experimental_solver_backend == 'experimental_cuda':
            from service.application.feedback.gpu_replay import (
                iter_gpu_replay_batches,
                replay_gpu_batch,
            )

            requests = []
            for body in ids:
                item = prepared['targets'].get(body) if prepared else None
                overrides = ({int(key): value for key, value in item['nseg_by_edge'].items()}
                             if item else {})
                requests.append({'id': body, 'expected_sha256': morphology_hashes[body],
                                 'events': item['effective_events'] if item else events[body],
                                 'nseg_by_edge': overrides})
            gpu_options = ({'allow_table_clamp': True} if experimental_gpu_allow_table_clamp
                           else {})
            if gpu_progress is not None:
                gpu_options['progress'] = gpu_progress
            if gpu_geometry_cache is not None:
                gpu_options['geometry_cache'] = gpu_geometry_cache
            if experimental_gpu_stream_cells is not None:
                output = iter_gpu_replay_batches(requests, directories, simulation,
                    max_cells=experimental_gpu_stream_cells,
                    output_budget_bytes=experimental_gpu_output_budget_bytes, **gpu_options)
            else:
                output = replay_gpu_batch(requests, directories, simulation,
                    output_budget_bytes=experimental_gpu_output_budget_bytes, **gpu_options)
                if len(output) != len(ids):
                    raise ValueError('Incomplete GPU feedback replay')
            for completed, (body, item) in enumerate(zip(ids, output, strict=True), 1):
                if (item.get('id') != body
                        or item.get('morphology_sha256') != morphology_hashes[body]
                        or item.get('provenance', {}).get('body_id') != str(body)):
                    raise ValueError('GPU feedback morphology identity mismatch')
                solution, proof = item['arrays'], item['provenance']
                clamped = proof.get('experimental_hh_table_clamped')
                if (type(clamped) is not bool
                        or (clamped and not experimental_gpu_allow_table_clamp)):
                    raise ValueError('Invalid GPU HH table boundary receipt')
                if clamped:
                    clamped_cell_ids.append(body)
                if solution_sink is not None:
                    solution_sink(body, solution, proof)
                yield solution, proof
                if cell_progress is not None:
                    cell_progress(completed, len(ids))
            return
        results = ordered_process_map(_solve_cell, tasks(), workers=experimental_cell_workers)
        try:
            for completed, (body, cache_key, solution, proof, cached) in enumerate(results, 1):
                if body != ids[completed - 1]:
                    raise ValueError('Population worker result order mismatch')
                if (str(proof.get('body_id')) != str(body)
                        or proof.get('morphology_sha256') != morphology_hashes[body]):
                    raise ValueError('Population morphology identity mismatch')
                if cell_cache is not None and not cached:
                    cell_cache.put(cache_key, (solution, proof), group=body)
                if solution_sink is not None:
                    solution_sink(body, solution, proof)
                yield solution, proof
                if cell_progress is not None:
                    cell_progress(completed, len(ids))
        finally:
            results.close()

    records = solutions()
    try:
        recording = record_independent_cells(
            records, settings['electrode_um'], settings['reference_um'],
            source_model=settings['source_model'], provenance_sink=provenance_sink)
    finally:
        records.close()
    if recording['cells'] != len(ids):
        raise ValueError('Population recording is incomplete')
    return {'source_ids': ids.copy(), 'source_configuration_sha256': config.digest(),
            'feedback_event_count': schedule['event_count'],
            'incomplete_pairs': omitted_pairs.copy(),
            'unresolved_candidates': len(unresolved),
            **({'experimental_solver_backend': experimental_solver_backend}
               if experimental_solver_backend is not None else {}),
            **({'experimental_cell_workers': experimental_cell_workers}
               if experimental_cell_workers != 1 else {}),
            **({'experimental_gpu_table_clamped_cell_ids': clamped_cell_ids}
               if experimental_solver_backend == 'experimental_cuda' else {}),
            **({'discretization': prepared} if prepared is not None else {}),
            'recording': recording,
            'interpretation': 'one physical population replay using fixed uncalibrated feedback; '
                              'not closed-loop and not a full-network physical recording'}
