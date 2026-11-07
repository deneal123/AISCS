import hashlib
import json

import numpy as np
import pytest

from service.application.replay.fragment_target_replay import (
    combine_fragment_target_recording,
    replay_fragment_target,
    replay_fragment_target_population,
    target_voltage_probe,
)


def test_target_replay_requires_matching_field_and_subtracts_baseline(monkeypatch):
    module = 'service.application.replay.fragment_target_replay.'
    configuration = {'field': 'same'}
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    diagnostic = {'simulation_sha256': digest}
    monkeypatch.setattr(module + 'match_fragment_inputs', lambda *_a, **_kw: {
        'target_morphology_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'schedule_matched_fragment_events', lambda *_a, **_kw: {
        'events': [{'time_ms': 1, 'child_node_id': 9, 'position': .5}]})
    monkeypatch.setattr(module + 'simulate_registered_swc_reference', lambda *_a, **kw: (
        {'time_ms': np.array([0., 1.]), 'edge_node_ids': np.array([9]),
         'voltage_mv': np.array([[-65., -64.]]),
         'active': 'synaptic_events' in kw},
        {'configuration': configuration}))
    monkeypatch.setattr(module + 'record_swc_with_stimulus_artifact', lambda result, *_a, **_kw: {
        'neural_uv': np.array([0., 2. if result['active'] else 1.]),
        'stimulus_artifact_uv': np.array([0., 3.])})
    kwargs = {'simulation_parameters': {'duration_ms': 2, 'nseg_per_edge': 1},
              'recording': {'electrode_um': [0, 0, 0], 'reference_um': [1, 0, 0],
                            'source_model': 'pointsource'},
              'schedule_parameters': {'duration_ms': 2}, 'max_source_distance_um': 2,
              'max_target_distance_um': 2}
    result = replay_fragment_target(diagnostic, None, None, 20, [], **kwargs)
    np.testing.assert_array_equal(result['delta_neural_uv'], [0, 1])
    assert result['voltage_probe']['child_node_id'] == 9
    np.testing.assert_array_equal(result['voltage_probe']['active_mv'], [-65, -64])
    with pytest.raises(ValueError, match='configuration differs'):
        replay_fragment_target({'simulation_sha256': 'b' * 64}, None, None, 20, [], **kwargs)


def test_combined_recording_counts_stimulus_artifact_once_and_rejects_overlap():
    settings = {'electrode_um': [1, 0, 0], 'reference_um': [2, 0, 0], 'source_model': 'pointsource'}
    source = {**settings, 'cells': 1, 'time_ms': [0., 1.], 'neural_uv': [1., 2.],
              'stimulus_artifact_uv': [0., 3.], 'total_uv': [1., 5.]}
    replay = {'mapping': {'source_id': 10, 'target_id': 20}, 'recording': settings,
              'time_ms': [0., 1.], 'active_neural_uv': [4., 5.],
              'stimulus_artifact_uv': [0., 3.]}
    result = combine_fragment_target_recording(source, replay, source_ids=[10])
    np.testing.assert_array_equal(result['neural_uv'], [5., 7.])
    np.testing.assert_array_equal(result['total_uv'], [5., 10.])
    with pytest.raises(ValueError, match='incompatible'):
        combine_fragment_target_recording(
            source, {**replay, 'mapping': {'source_id': 10, 'target_id': 10}}, source_ids=[10])
    with pytest.raises(ValueError, match='artifacts differ'):
        combine_fragment_target_recording(source, {**replay, 'stimulus_artifact_uv': [0., 4.]},
                                          source_ids=[10])
    multi = {**source, 'cells': 2}
    multi_replay = {**replay, 'mapping': {'source_ids': [10, 11], 'target_id': 20}}
    result = combine_fragment_target_recording(multi, multi_replay, source_ids=[10, 11])
    np.testing.assert_array_equal(result['total_uv'], [5., 10.])
    with pytest.raises(ValueError, match='incompatible'):
        combine_fragment_target_recording(multi, {**multi_replay,
            'mapping': {'source_ids': [10, 10], 'target_id': 20}}, source_ids=[10, 11])


def test_population_replay_combines_sources_once_and_rejects_incompatible_fields(monkeypatch):
    module = 'service.application.replay.fragment_target_replay.'
    configuration = {'field': 'same'}
    digest = hashlib.sha256(json.dumps(configuration, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    def match(diagnostic, *_a, **_kw):
        return {'source_id': diagnostic['source_id'], 'target_id': 20,
                'target_morphology_sha256': 'b' * 64, 'graph_sha256': 'a' * 64,
                'candidates': [{'target_child_node_id': diagnostic['source_id'],
                                'target_fraction': .5, 'stimulated_ticks_ms': [1]}]}
    monkeypatch.setattr(module + 'match_fragment_inputs', match)
    calls = []
    def simulate(*_a, **kwargs):
        calls.append(kwargs)
        return ({'time_ms': np.array([0., 1.]), 'edge_node_ids': np.array([10]),
                 'voltage_mv': np.array([[-65., -64.]]),
                 'active': 'synaptic_events' in kwargs}, {'configuration': configuration})
    monkeypatch.setattr(module + 'simulate_registered_swc_reference', simulate)
    monkeypatch.setattr(module + 'record_swc_with_stimulus_artifact', lambda result, *_a, **_kw: {
        'neural_uv': np.array([0., 2. if result['active'] else 1.]),
        'stimulus_artifact_uv': np.array([0., 3.])})
    sources = [{'source_id': 10, 'simulation_sha256': digest},
               {'source_id': 11, 'simulation_sha256': digest}]
    parameters = {'delay_ms': 0, 'duration_ms': 2, 'weight_us': .01,
                  'tau1_ms': .2, 'tau2_ms': 2, 'reversal_mv': 0}
    kwargs = {'simulation_parameters': {'duration_ms': 2, 'nseg_per_edge': 1},
              'recording': {'electrode_um': [0, 0, 0], 'reference_um': [1, 0, 0],
                            'source_model': 'pointsource'},
              'schedule_parameters': [parameters, parameters], 'max_events': 4,
              'max_source_distance_um': 2, 'max_target_distance_um': 2}
    result = replay_fragment_target_population(sources, None, None, 20, [], **kwargs)
    assert result['mapping']['source_ids'] == [10, 11]
    assert [row['source_id'] for row in result['schedule']['evidence']] == [10, 11]
    assert len(calls) == 2 and len(calls[1]['synaptic_events']) == 2
    np.testing.assert_array_equal(result['delta_neural_uv'], [0, 1])
    with pytest.raises(ValueError, match='Incompatible source field'):
        replay_fragment_target_population([sources[0], {**sources[1],
            'simulation_sha256': 'c' * 64}], None, None, 20, [], **kwargs)


def test_probe_identifies_the_compartment_and_rejects_wrong_geometry():
    solution = {'time_ms': [0, 1], 'edge_node_ids': [4, 4, 4, 5, 5, 5],
                'voltage_mv': np.arange(12).reshape(6, 2)}
    event = {'child_node_id': 5, 'position': 1.0}
    probe = target_voltage_probe(solution, solution, [event], 3)
    assert (probe['child_node_id'], probe['segment_index']) == (5, 2)
    assert probe['segment_center'] == 5 / 6
    np.testing.assert_array_equal(probe['active_mv'], [10, 11])
    assert target_voltage_probe(solution, solution, [], 3) is None
    with pytest.raises(ValueError, match='not found'):
        target_voltage_probe(solution, solution, [{'child_node_id': 6, 'position': .5}], 3)
