from types import SimpleNamespace

import pytest

from service.application.population.full_feedback_experiment import execute_full_feedback_experiment
from tests.test_fragment_population_contract import example


def test_experiment_authenticates_cache_and_passes_stimulation(tmp_path, monkeypatch):
    module = 'service.application.population.full_feedback_experiment.'
    graph = SimpleNamespace(ids=[10, 20], provenance={'manifest_sha256': 'a' * 64})
    sources = {10: 'b' * 64, 20: 'c' * 64}
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'd' * 64}
    monkeypatch.setattr(module + 'audited_geometry_sources', lambda *_a: (sources, 'e' * 64))
    monkeypatch.setattr(module + 'read_manifest', lambda *_a, **_k: {'graph_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: ('table', None))
    received = {}

    def run(metadata, stimulus, table, **kwargs):
        received.update(metadata=metadata, stimulus=stimulus, table=table, **kwargs)
        return {'status': 'converged'}

    monkeypatch.setattr(module + 'run_full_population_from_geometry', run)
    parameters = {1: {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}}
    result = execute_full_feedback_experiment(graph, object(), example()['simulation'],
        geometry_cache=cache, output_directory=tmp_path / 'result', directories=[],
        synapse_parameters=parameters, threshold_mv=-20., max_source_distance_um=2.,
        max_target_distance_um=2., max_iterations=3, max_events=100,
        solver_options={'segment_budget': 1000, 'output_budget_bytes': 10000})
    assert result['status'] == 'converged'
    assert received['source_ids'] == [10, 20]
    assert received['replay_options']['audited_sources'] == sources
    assert received['replay_options']['duration_ms'] == 10
    assert received['replay_options']['max_source_distance_um'] == 2.
    assert received['synapse_parameters'] == parameters
    assert len(received['configuration_sha256']) == 64
    assert len(received['baseline_sha256']) == 64


def test_experiment_rejects_known_unresolved_geometry(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
        KNOWN_SOURCE_SHA256,
    )

    module = 'service.application.population.full_feedback_experiment.'
    graph = SimpleNamespace(ids=[842998], provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'audited_geometry_sources',
                        lambda *_a: ({842998: KNOWN_SOURCE_SHA256}, 'e' * 64))
    monkeypatch.setattr(module + 'read_manifest', lambda *_a, **_k: {})
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'd' * 64}
    with pytest.raises(ValueError, match='repaired cell'):
        execute_full_feedback_experiment(graph, object(), example()['simulation'],
            geometry_cache=cache, output_directory=tmp_path / 'result', directories=[],
            synapse_parameters={}, threshold_mv=-20., max_source_distance_um=2.,
            max_target_distance_um=2., max_iterations=3, max_events=100, solver_options={})


def test_explicit_repair_preserves_source_and_derived_identities(tmp_path, monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu.known_geometry_repair import (
        KNOWN_SOURCE_SHA256,
    )

    module = 'service.application.population.full_feedback_experiment.'
    graph = SimpleNamespace(ids=[842998], provenance={'manifest_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'audited_geometry_sources',
                        lambda *_a: ({842998: KNOWN_SOURCE_SHA256}, 'e' * 64))
    monkeypatch.setattr(module + 'read_manifest', lambda *_a, **_k: {})
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: ('table', None))
    receipt = {'source_sha256': KNOWN_SOURCE_SHA256, 'derived_sha256': 'f' * 64}
    monkeypatch.setattr(module + 'known_zero_edge_identity', lambda *_a: receipt)
    monkeypatch.setattr(module + 'known_zero_edge_replacement', lambda *_a: 'replacement')
    captured = {}
    monkeypatch.setattr(module + 'run_full_population_from_geometry',
                        lambda *_a, **kwargs: captured.update(kwargs))
    cache = {'directory': tmp_path, 'source_index': tmp_path / 'index',
             'source_audit': tmp_path / 'audit', 'expected_manifest_sha256': 'd' * 64}
    execute_full_feedback_experiment(graph, object(), example()['simulation'],
        geometry_cache=cache, output_directory=tmp_path / 'result', directories=[],
        synapse_parameters={}, threshold_mv=-20., max_source_distance_um=2.,
        max_target_distance_um=2., max_iterations=3, max_events=100, solver_options={},
        allow_known_geometry_repair=True, target_provider=lambda _: None)
    assert captured['morphology_sha256'] == {842998: 'f' * 64}
    assert captured['replay_options']['audited_sources'] == {842998: KNOWN_SOURCE_SHA256}
    assert captured['configuration']['geometry_repair'] == receipt
    verify = captured['replay_options']['on_replacement']
    verify(842998, 7, receipt)
    with pytest.raises(ValueError, match='repair identity'):
        verify(842998, 7, {**receipt, 'derived_sha256': '0' * 64})


def test_request_binds_operator_configuration_and_rejects_wrong_graph(tmp_path, monkeypatch):
    from service.application.population.full_feedback_experiment import (
        execute_full_feedback_request,
    )
    from service.domain.contracts.population.full_feedback import FullFeedbackConfig

    synapse = {'weight_us': .01, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}
    request = {'graph_manifest_sha256': 'a' * 64, 'simulation': example()['simulation'],
        'excitatory': synapse, 'inhibitory': {**synapse, 'reversal_mv': -80.},
        'threshold_mv': -20., 'max_source_distance_um': 2., 'max_target_distance_um': 2.,
        'max_iterations': 3, 'max_events': 100}
    seen = {}
    monkeypatch.setattr('service.application.population.full_feedback_experiment.'
                        'execute_full_feedback_experiment',
                        lambda *_a, **kwargs: seen.update(kwargs))
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    execute_full_feedback_request(graph, object(), request, geometry_cache={},
        output_directory=tmp_path / 'result', directories=[], solver_options={})
    assert seen['request_sha256'] == FullFeedbackConfig.model_validate(request).digest()
    assert seen['synapse_parameters'][1]['reversal_mv'] == 0.
    assert seen['synapse_parameters'][-1]['reversal_mv'] == -80.
    graph.provenance['manifest_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='graph mismatch'):
        execute_full_feedback_request(graph, object(), request, geometry_cache={},
            output_directory=tmp_path / 'result', directories=[], solver_options={})
