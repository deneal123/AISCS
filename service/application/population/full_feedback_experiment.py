"""Prepare full detailed-cell feedback using the simulator's experiment settings."""

import hashlib
import json
import math
import re

from service.application.feedback.fixed_inputs import fixed_input_digest
from service.application.feedback.full_population import run_full_population_from_geometry
from service.application.population.bulk_simulation_inputs import bulk_simulation_inputs
from service.domain.contracts.population.full_feedback import FullFeedbackConfig
from service.domain.contracts.replay import ReplaySimulation
from service.infrastructure.stimulation.experimental_gpu.fast_prepare import read_manifest
from service.infrastructure.stimulation.experimental_gpu.hh_table import prepare_hh_table
from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
    KNOWN_SOURCE_SHA256,
    known_zero_edge_identity,
    known_zero_edge_replacement,
)
from service.infrastructure.stimulation.geometry_cache.index import audited_geometry_sources
from service.infrastructure.stimulation.population.cached_targets import (
    known_derived_target,
    population_target_provider,
)


def execute_full_feedback_experiment(graph, index, simulation, *, geometry_cache,
        output_directory, directories, synapse_parameters, threshold_mv, max_source_distance_um,
        max_target_distance_um, max_iterations, max_events, solver_options,
        target_provider=None, pair_cache=None, allow_known_geometry_repair=False,
        request_sha256=None, progress=None):
    """Prepare a coupled run; no biological validation or runtime guarantee is implied.

    The caller supplies trusted paths, resource limits and synaptic assumptions.
    No result is published if morphology coverage or convergence is incomplete.
    """
    config = ReplaySimulation.model_validate(simulation)
    duration = config.duration_ms
    if (not math.isfinite(duration) or duration != int(duration) or duration < 1
            or config.nseg_per_edge != 1 or not isinstance(solver_options, dict)
            or type(allow_known_geometry_repair) is not bool
            or (request_sha256 is not None and (not isinstance(request_sha256, str)
                or not re.fullmatch('[a-f0-9]{64}', request_sha256)))):
        raise ValueError('Full feedback requires integer milliseconds and one segment per edge')
    graph_hash = graph.provenance['manifest_sha256']
    sources, source_hash = audited_geometry_sources(
        geometry_cache['source_index'], geometry_cache['source_audit'], graph.ids, graph_hash)
    metadata = read_manifest(geometry_cache['directory'],
        expected_manifest_sha256=geometry_cache['expected_manifest_sha256'],
        graph_sha256=graph_hash, source_index_sha256=source_hash)
    repair = None
    morphology_hashes = sources.copy()
    if sources.get(842998) == KNOWN_SOURCE_SHA256:
        if not allow_known_geometry_repair:
            raise ValueError('Full feedback requires verified geometry identity for repaired cell')
        repair = known_zero_edge_identity(directories)
        morphology_hashes[842998] = repair['derived_sha256']
    ids = [int(body) for body in graph.ids]
    if list(sources) != ids:
        raise ValueError('Full feedback source order differs from registered graph')
    if target_provider is None:
        target_provider = population_target_provider(graph, morphology_hashes,
            geometry_cache=geometry_cache,
            derived_target=known_derived_target(directories) if repair is not None else None)
    elif not callable(target_provider):
        raise ValueError('Invalid full feedback target provider')
    parameters = bulk_simulation_inputs(config)
    stimulus = parameters.pop('stimulus')
    configuration = {'simulation': config.model_dump(mode='json'),
        'synapse_parameters': synapse_parameters, 'threshold_mv': threshold_mv,
        'max_source_distance_um': max_source_distance_um,
        'max_target_distance_um': max_target_distance_um,
        'max_iterations': max_iterations, 'max_events': max_events,
        'graph_sha256': graph_hash, 'source_index_sha256': source_hash,
        'geometry_cache_manifest_sha256': geometry_cache['expected_manifest_sha256'],
        'geometry_repair': repair, 'request_sha256': request_sha256}
    try:
        raw = json.dumps(configuration, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode('utf8')
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid full feedback configuration') from exc
    config_hash = hashlib.sha256(raw).hexdigest()
    provenance = {body: [] for body in ids}
    proof_hash = hashlib.sha256(json.dumps({str(body): [] for body in ids}, sort_keys=True,
        separators=(',', ':')).encode('utf8')).hexdigest()
    baseline = {'graph_sha256': graph_hash, 'source_ids': ids,
        'target_morphology_sha256': {}, 'events_by_target': {body: [] for body in ids},
        'provenance_by_target': provenance, 'provenance_sha256': proof_hash,
        'event_count': 0, 'outside_window': 0, 'unresolved': []}
    if set(parameters).intersection(solver_options) or any(
            key in solver_options for key in ('expected_ids', 'audited_sources', 'duration_ms',
                                               'threshold_mv', 'max_source_distance_um')):
        raise ValueError('Conflicting full feedback solver options')
    if repair is not None:
        if 'replacement_factory' in solver_options or 'on_replacement' in solver_options:
            raise ValueError('Conflicting full feedback geometry repair policy')

        def verify_replacement(body, code, receipt):
            if body != 842998 or code != 7 or receipt != repair:
                raise ValueError('Full feedback geometry repair identity mismatch')

        solver_options = {**solver_options,
            'replacement_factory': known_zero_edge_replacement(directories, parameters['params']),
            'on_replacement': verify_replacement}
    replay = {**parameters, **solver_options, 'expected_ids': ids, 'audited_sources': sources,
              'duration_ms': int(duration), 'threshold_mv': threshold_mv,
              'max_source_distance_um': max_source_distance_um}
    table, _ = prepare_hh_table()
    return run_full_population_from_geometry(metadata, stimulus, table, graph=graph, index=index,
        source_ids=ids, morphology_sha256=morphology_hashes, configuration_sha256=config_hash,
        baseline_schedule=baseline, baseline_sha256=fixed_input_digest(baseline),
        output_directory=output_directory, directories=directories,
        synapse_parameters=synapse_parameters, replay_options=replay,
        max_source_distance_um=max_source_distance_um,
        max_target_distance_um=max_target_distance_um,
        max_iterations=max_iterations, max_events=max_events, target_provider=target_provider,
        pair_cache=pair_cache, configuration=configuration, export_markers=True, progress=progress)


def execute_full_feedback_request(graph, index, config, *, geometry_cache, output_directory,
                                  directories, solver_options, target_provider=None,
                                  pair_cache=None, progress=None):
    """Bind one validated operator request to the full-population workflow."""
    config = FullFeedbackConfig.model_validate(config)
    if graph.provenance.get('manifest_sha256') != config.graph_manifest_sha256:
        raise ValueError('Full feedback request graph mismatch')
    return execute_full_feedback_experiment(graph, index, config.simulation,
        geometry_cache=geometry_cache, output_directory=output_directory,
        directories=directories, synapse_parameters=config.parameters(),
        threshold_mv=config.threshold_mv, max_source_distance_um=config.max_source_distance_um,
        max_target_distance_um=config.max_target_distance_um, max_iterations=config.max_iterations,
        max_events=config.max_events, solver_options=solver_options,
        target_provider=target_provider,
        pair_cache=pair_cache, allow_known_geometry_repair=config.allow_known_geometry_repair,
        request_sha256=config.digest(), progress=progress)
