"""Prepare an independent GPU recording from registered experiment inputs."""

from service.application.population.bulk_recording_execution import execute_bulk_recording
from service.application.population.bulk_simulation_inputs import bulk_simulation_inputs
from service.domain.contracts.population.bulk_recording import BulkRecordingConfig
from service.domain.contracts.replay import ReplaySimulation
from service.infrastructure.stimulation.experimental_gpu.fast_prepare import read_manifest
from service.infrastructure.stimulation.experimental_gpu.hh_table import prepare_hh_table
from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
    KNOWN_SOURCE_SHA256,
)
from service.infrastructure.stimulation.geometry_cache.index import audited_geometry_sources


def execute_bulk_experiment(graph, simulation, *, geometry_cache, output_path, progress=None,
                            solver_options, replacement_builder=None):
    """Run independent cells and record E1–REF; no network response is computed.

    Cache paths and resource limits must come from trusted server configuration.
    The caller is responsible for isolated execution and publishing the artifact.
    """
    graph_hash = graph.provenance['manifest_sha256']
    config = ReplaySimulation.model_validate(simulation)
    parameters = bulk_simulation_inputs(config)
    sources, source_hash = audited_geometry_sources(
        geometry_cache['source_index'], geometry_cache['source_audit'], graph.ids, graph_hash)
    metadata = read_manifest(geometry_cache['directory'],
        expected_manifest_sha256=geometry_cache['expected_manifest_sha256'],
        graph_sha256=graph_hash, source_index_sha256=source_hash)
    if sources.get(842998) == KNOWN_SOURCE_SHA256 and replacement_builder is None:
        raise ValueError('Known zero-edge morphology requires explicit verified repair policy')
    configuration_hash = BulkRecordingConfig(graph_manifest_sha256=graph_hash,
                                              simulation=config).digest()
    if replacement_builder is not None:
        if not callable(replacement_builder) or 'replacement_factory' in solver_options:
            raise ValueError('Invalid geometry replacement policy')
        solver_options = {**solver_options,
                          'replacement_factory': replacement_builder(parameters['params'])}
    table, _ = prepare_hh_table()
    stimulus = parameters.pop('stimulus')
    result = execute_bulk_recording(metadata, stimulus, table, output_path=output_path,
        graph_sha256=graph_hash, configuration_sha256=configuration_hash,
        audited_sources=sources, expected_ids=list(sources), progress=progress,
        **parameters, **solver_options)
    result['geometry_cache_manifest_sha256'] = geometry_cache['expected_manifest_sha256']
    result['source_index_sha256'] = source_hash
    return result
