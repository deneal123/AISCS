"""Experimental fixed-point replay of a verified physical source population.

The LIF network and individual physical cells use different models. The loop
requires explicit synapse parameters and does not establish physiology.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from service.application.feedback.cell_solution_cache import CellSolutionCache
from service.application.feedback.lif_feedback_mapping import map_lif_feedback
from service.application.feedback.population_feedback_outputs import feedback_output_events
from service.application.feedback.population_feedback_replay import replay_population_feedback
from service.application.feedback.population_feedback_schedule import population_feedback_schedule
from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.connectome.edge_forced_network import run_edge_forced_network
from service.infrastructure.connectome.source_feedback import suppressed_source_inputs
from service.infrastructure.stimulation.fragment_pair_mapping import match_fragment_inputs
from service.infrastructure.stimulation.fragment_population_archive import (
    load_verified_fragment_population,
)
from service.infrastructure.stimulation.population_feedback_checkpoint import (
    checkpoint_run_identity,
    read_checkpoint,
    write_checkpoint,
)


def iterate_population_feedback(path, graph, index, directories, *, parameters,
                                max_iterations, allow_partial_geometry=False, progress=None,
                                checkpoint_dir=None, resume_from=None,
                                discretization_policy=None, stage_progress=None,
                                experimental_cache_bytes=0):
    """Iterate a single verified batch, refusing unsupported network feedback.

    The result is explicitly partial when any candidate geometry is unresolved.
    No result is published by this function; callers must persist provenance.
    """
    if (type(max_iterations) is not int or not 1 <= max_iterations <= 100
            or type(experimental_cache_bytes) is not int or experimental_cache_bytes < 0
            or type(allow_partial_geometry) is not bool
            or (progress is not None and not callable(progress))
            or (stage_progress is not None and not callable(stage_progress))
            or (checkpoint_dir is not None
                and (not isinstance(checkpoint_dir, Path) or not checkpoint_dir.is_dir()))
            or (resume_from is not None and not isinstance(resume_from, Path))):
        raise ValueError('Invalid feedback iteration settings')
    # Checkpoints and published archives do not yet preserve these receipts.
    # Never silently resume or publish a differently discretized calculation.
    if (discretization_policy is not None
            and (checkpoint_dir is not None or resume_from is not None)):
        raise ValueError('Discretization is not supported by feedback checkpoints')
    cell_cache = (CellSolutionCache(experimental_cache_bytes, policy='stable')
                  if experimental_cache_bytes else None)
    original = load_verified_fragment_population(path, graph)
    metadata = original['metadata']
    config = FragmentPopulationConfig.model_validate(metadata['configuration'])
    if discretization_policy is not None:
        index_manifest = getattr(index, 'manifest', None)
        graph_provenance = getattr(graph, 'provenance', {})
        arrays = (graph_provenance.get('array_sha256', {})
                  if isinstance(graph_provenance, dict) else {})
        if (not isinstance(discretization_policy, dict) or not isinstance(index_manifest, dict)
                or not isinstance(arrays, dict) or not arrays.get('ids.npy')
                or index_manifest.get('ids_sha256') != arrays['ids.npy']
                or index_manifest.get('source_md5')
                   != discretization_policy.get('expected_source_md5')):
            raise ValueError('Discretization index and graph identity mismatch')
    source_unresolved = sum(len(row.get('unresolved_geometry', []))
                            for row in metadata['schedules'])
    if source_unresolved and not allow_partial_geometry:
        raise ValueError('Partial source geometry requires explicit partial feedback')
    ids = config.source_ids
    diagnostics = {int(row['body_id']): row for row in metadata['diagnostics']}
    hashes = {body: diagnostics[body]['morphology_sha256'] for body in ids}
    local = {body: [{'source_position_8nm': row['source_position_8nm'],
                     'partner_id': row['partner_id'],
                     'stimulated_ticks_ms': row['stimulated_ticks_ms']}
                    for row in diagnostics[body]['candidates'] if row['included_in_graph']
                    and (config.allow_partial_geometry is not True
                         or row['centerline_distance_um'] <= config.max_distance_um)]
             for body in ids}
    edges = [event for item in metadata['schedules'] for event in item['edge_events']]
    duration = int(config.simulation.duration_ms)
    cache, lif_geometry_cache, seen, history = {}, {}, set(), []
    previous, replay = None, None
    discretizations = []

    def discretization_provenance():
        return ({'discretization_receipts': copy.deepcopy(discretizations)}
                if discretization_policy is not None else {})

    def physical_output():
        # Preserve the source-population events that actually drove this graph
        # run. Network spikes alone exclude these physically simulated cells.
        result = {'source_ids': ids.copy(), 'edge_events': copy.deepcopy(edges),
                'candidate_events_by_source': copy.deepcopy(local),
                'source_configuration_sha256': config.digest(),
                'source_morphology_sha256': hashes.copy(),
                'graph_sha256': config.graph_manifest_sha256,
                'threshold_mv': config.threshold_mv,
                'interpretation': 'threshold crossings of candidate segments in physically '
                                  'simulated source cells; not full-network physical spikes'}
        if config.allow_partial_geometry is True:
            result['source_unresolved_graph_pairs'] = source_unresolved
        return result

    run_identity = None
    if checkpoint_dir is not None or resume_from is not None:
        run_identity = checkpoint_run_identity(original.get('manifest'),
                                               getattr(index, 'manifest', None))
    if resume_from is not None:
        state = read_checkpoint(resume_from, config=config, diagnostics=diagnostics,
            parameters=parameters, allow_partial_geometry=allow_partial_geometry,
            run_identity=run_identity)
        history = state['history']
        if len(history) >= max_iterations:
            raise ValueError('Maximum iterations must exceed the checkpoint iteration')
        local = {int(body): rows for body, rows in state['local'].items()}
        edges = state['edges']
        previous = history[-1]['schedule_sha256']
        seen = {row['schedule_sha256'] for row in history}
        recording = state['recording']
        for name in ('time_ms', 'neural_uv', 'stimulus_artifact_uv',
                     'stimulus_fraction', 'total_uv'):
            recording[name] = np.asarray(recording[name], dtype=float)
        replay = {'recording': recording}
    for iteration in range(len(history), max_iterations):
        if stage_progress is not None:
            stage_progress({'phase': 'feedback_network', 'iteration': iteration + 1,
                            'done': 0, 'total': 0})
        network = run_edge_forced_network(graph, seed=config.seed, duration_ms=duration,
                                          forced_cell_ids=ids, edge_events=edges,
                                          capture_sparse_delta=True)
        feedback = suppressed_source_inputs(graph, ids, edges, network, duration_ms=duration)
        pairs = sorted({(row['source_id'], row['target_id']) for row in feedback['events']
                        if row['kind'] == 'physical-source-edge'})
        mappings = map_lif_feedback(graph, index, directories, feedback, ids,
            max_distance_um=config.max_distance_um, allow_partial=allow_partial_geometry,
            _geometry_cache=lif_geometry_cache)
        for source, target in pairs:
            pair = (source, target)
            if pair not in cache:
                cache[pair] = match_fragment_inputs(
                    diagnostics[source], index, graph, target, directories,
                    max_source_distance_um=config.max_distance_um,
                    max_target_distance_um=config.max_distance_um, duration_ms=duration,
                    allow_partial=allow_partial_geometry,
                    allow_partial_source=config.allow_partial_geometry is True)
            mapping = copy.deepcopy(cache[pair])
            ticks = {(row['partner_id'], *row['source_position_8nm']): row['stimulated_ticks_ms']
                     for row in local[source]}
            for candidate in mapping['candidates'] + mapping.get('unresolved_target_geometry', []):
                key = (str(target), *candidate['source_position_8nm'])
                if key not in ticks:
                    raise ValueError('Missing updated feedback output')
                candidate['stimulated_ticks_ms'] = ticks[key]
                candidate.pop('stimulated_crossing_intervals', None)
            mappings.append(mapping)
        schedule = population_feedback_schedule(ids, feedback, mappings, parameters,
            duration_ms=duration, max_events=1_000_000,
            allow_partial_geometry=allow_partial_geometry)
        signature = hashlib.sha256(json.dumps(
            {'events': schedule['events_by_target'], 'unresolved': schedule['unresolved']},
            sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if previous == signature:
            if replay is None:
                raise ValueError('Missing physical replay')
            return {'status': 'converged_partial' if schedule['unresolved'] or source_unresolved
                    else 'converged',
                    'iterations': history, 'recording': replay['recording'],
                    'network': network, 'schedule': schedule,
                    'physical_source_output': physical_output(),
                    **discretization_provenance(),
                    'feedback_alignment': 'schedule_matches_last_replay'}
        if signature in seen:
            if replay is None:
                raise ValueError('Missing physical replay')
            return {'status': 'cycle_detected', 'iterations': history,
                    'recording': replay['recording'], 'network': network,
                    'physical_source_output': physical_output(),
                    **discretization_provenance(),
                    'pending_feedback': feedback,
                    'feedback_alignment': 'network_feedback_not_applied_to_last_replay'}
        seen.add(signature)
        next_edges, next_local = [], {}

        def capture(body, solution, proof, edge_sink=next_edges, local_sink=next_local):
            result = feedback_output_events(body, solution, proof, diagnostics[body],
                threshold_mv=config.threshold_mv, duration_ms=duration, include_candidates=True,
                **({'max_source_distance_um': config.max_distance_um}
                   if config.allow_partial_geometry is True else {}))
            edge_sink.extend(result['edge_events'])
            local_sink[body] = result['candidates']

        omitted = sorted({(row['source_id'], row['target_id']) for row in schedule['unresolved']})
        replay_options = ({'discretization_policy': discretization_policy, 'synapse_index': index}
                          if discretization_policy is not None else {})
        if cell_cache is not None:
            replay_options['cell_cache'] = cell_cache
        if stage_progress is not None:
            def report_cell(done, total, current=iteration + 1):
                stage_progress({'phase': 'feedback_cells', 'iteration': current,
                                'done': done, 'total': total})
            replay_options['cell_progress'] = report_cell
        replay = replay_population_feedback(config, directories, schedule, hashes,
                                             omitted_pairs=omitted, solution_sink=capture,
                                             **replay_options)
        if discretization_policy is not None:
            discretizations.append(copy.deepcopy(replay['discretization']))
        history.append({'iteration': iteration + 1, 'schedule_sha256': signature,
                        'input_events': schedule['event_count'],
                        'unresolved_events': sum(len(row['stimulated_ticks_ms'])
                                                 for row in schedule['unresolved']),
                        'outside_window': schedule['outside_window'],
                        'output_edge_records': len(next_edges),
                        'network_spikes': len(network['spike_neurons'])})
        if checkpoint_dir is not None:
            checkpoint = {'format': 'population-feedback-checkpoint-v1',
                'configuration_sha256': config.digest(),
                'graph_sha256': config.graph_manifest_sha256,
                'run_identity': run_identity,
                'source_ids': ids.copy(), 'parameters': json.loads(json.dumps(parameters)),
                'allow_partial_geometry': allow_partial_geometry, 'history': history,
                'applied_schedule': json.loads(json.dumps(schedule, allow_nan=False)),
                'local': {str(body): rows for body, rows in next_local.items()},
                'edges': next_edges, 'recording': replay['recording']}
            checkpoint_path = checkpoint_dir / f'iteration-{iteration + 1:04d}.json'
            write_checkpoint(checkpoint_path, checkpoint)
            read_checkpoint(checkpoint_path, config=config, diagnostics=diagnostics,
                            parameters=parameters, allow_partial_geometry=allow_partial_geometry,
                            run_identity=run_identity)
        if progress is not None:
            progress(dict(history[-1]))
        local, edges, previous = next_local, next_edges, signature
    # Recompute from the latest physical output. The new graph feedback has not
    # been applied to that physical recording and must not be presented as such.
    if stage_progress is not None:
        stage_progress({'phase': 'feedback_network', 'iteration': len(history),
                        'done': 0, 'total': 0})
    network = run_edge_forced_network(graph, seed=config.seed, duration_ms=duration,
        forced_cell_ids=ids, edge_events=edges, capture_sparse_delta=True)
    pending = suppressed_source_inputs(graph, ids, edges, network, duration_ms=duration)
    return {'status': 'iteration_limit', 'iterations': history, 'recording': replay['recording'],
            'network': network, 'schedule': schedule, 'pending_feedback': pending,
            'physical_source_output': physical_output(),
            **discretization_provenance(),
            'feedback_alignment': 'network_feedback_not_applied_to_last_replay'}
