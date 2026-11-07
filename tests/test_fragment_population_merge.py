from copy import deepcopy

import numpy as np
import pytest

from service.application.population.fragment_population_merge import merge_fragment_batches
from service.infrastructure.connectome.edge_forced_network import run_edge_forced_network
from tests.test_forced_network import graph
from tests.test_fragment_population_contract import example


def batch(source, signal, event):
    config = deepcopy(example())
    config['source_ids'] = [source]
    return {'manifest': {'configuration_sha256': str(source)},
            'metadata': {'configuration': config, 'schedules': [{'edge_events': [event]}]},
            'arrays': {'time_ms': np.array([0., 10.]), 'stimulus_fraction': np.array([0., 1.]),
                       'neural_uv': np.array(signal), 'stimulus_artifact_uv': np.array([5., 6.])}}


def test_combines_sources_and_recomputes_one_network(monkeypatch):
    first_event = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 10}
    second_event = {'source_id': 20, 'target_id': 30, 'tick': 1, 'count': 10}
    chunks = {'a': batch(10, [1., 2.], first_event), 'b': batch(20, [3., 4.], second_event)}
    monkeypatch.setattr('service.application.population.fragment_population_merge.load_verified_fragment_population',
                        lambda directory, _: chunks[directory])
    actual = merge_fragment_batches(graph(), ['a', 'b'])
    expected = run_edge_forced_network(graph(), seed=1, duration_ms=10, forced_cell_ids=[10, 20],
                                       edge_events=[first_event, second_event])
    np.testing.assert_array_equal(actual['neural_uv'], [4., 6.])
    np.testing.assert_array_equal(actual['total_uv'], [9., 12.])
    np.testing.assert_array_equal(actual['network']['counts'], expected['counts'])
    np.testing.assert_array_equal(actual['network']['final_voltage_relative_mv'],
                                  expected['final_voltage_relative_mv'])
    assert actual['source_ids'] == [10, 20]
    assert actual['source_targeted_edge_events'] == 1
    assert actual['source_targeted_synaptic_events'] == 10
    assert actual['network']['sparse_delta']['status'] == 'recorded'


def test_refuses_overlaps_and_mismatched_recording(monkeypatch):
    event = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 10}
    first = batch(10, [1., 2.], event)
    second = batch(20, [1., 2.], event)
    chunks = {'a': first, 'b': second}
    monkeypatch.setattr('service.application.population.fragment_population_merge.load_verified_fragment_population',
                        lambda directory, _: chunks[directory])
    with pytest.raises(ValueError, match='overlap'):
        merge_fragment_batches(graph(), ['a', 'a'])
    second['arrays']['stimulus_artifact_uv'][0] += 1
    with pytest.raises(ValueError, match='incompatible'):
        merge_fragment_batches(graph(), ['a', 'b'])
