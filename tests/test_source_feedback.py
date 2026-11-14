from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.source_feedback import suppressed_source_inputs
from tests.test_forced_network import graph


def test_tracks_physical_and_lif_inputs_with_delivery_delay_and_sign():
    edge = {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 7}
    spikes = {'spike_neurons': np.array([1]), 'spike_times_ms': np.array([3.])}
    result = suppressed_source_inputs(graph(-1), [10, 20, 30], [edge],
                                      {'spike_neurons': np.array([], dtype=int),
                                       'spike_times_ms': np.array([])}, duration_ms=6)
    event = result['events'][0]
    assert (event['source_id'], event['target_id'], event['synapse_count']) == (10, 20, 7)
    assert (event['emission_tick_ms'], event['delivery_tick_ms'],
            event['predicted_sign']) == (1, 3, -1)
    assert event['within_window'] is True
    result = suppressed_source_inputs(graph(), [10, 30], [], spikes, duration_ms=4)
    event = result['events'][0]
    assert event['kind'] == 'lif-network-spike'
    assert (event['source_id'], event['target_id'], event['synapse_count']) == (20, 30, 3000)
    assert event['delivery_tick_ms'] == 5 and event['within_window'] is False
    result = suppressed_source_inputs(graph(), [10, 30], [], spikes, duration_ms=5)
    assert result['events'][0]['delivery_tick_ms'] == 5
    assert result['events'][0]['within_window'] is True
    assert result['events'][0]['affects_replay'] is False


def test_rejects_unregistered_source_edges_and_spikes_of_suppressed_sources():
    empty = {'spike_neurons': np.array([], dtype=int), 'spike_times_ms': np.array([])}
    invalid = {'source_id': 10, 'target_id': 30, 'tick': 1, 'count': 1}
    with pytest.raises(ValueError, match='not registered'):
        suppressed_source_inputs(graph(), [10, 30], [invalid], empty, duration_ms=6)
    with pytest.raises(ValueError, match='graph events'):
        suppressed_source_inputs(graph(), [10], [],
            {'spike_neurons': np.array([0]), 'spike_times_ms': np.array([1.])}, duration_ms=6)
    repeated = [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1},
                {'source_id': 10, 'target_id': 20, 'tick': 2, 'count': 3001}]
    with pytest.raises(ValueError, match='not registered'):
        suppressed_source_inputs(graph(), [10, 20], repeated, empty, duration_ms=6)


def test_vectorized_feedback_preserves_repeated_spikes_and_edge_order():
    graph_data = SimpleNamespace(ids=np.array([10, 20, 30, 40]), size=4,
        ptr=np.array([0, 0, 3, 3, 3]), posts=np.array([0, 2, 3]),
        counts=np.array([2, 3, 4]), signs=np.array([1, -1, 1, 1]),
        provenance={'manifest_sha256': 'test'})
    network = {'spike_neurons': np.array([1, 1]), 'spike_times_ms': np.array([1., 3.])}
    events = suppressed_source_inputs(graph_data, [10, 30], [], network, duration_ms=5)['events']
    actual = [(row['target_id'], row['emission_tick_ms'], row['synapse_count']) for row in events]
    assert actual == [
        (10, 1, 2), (30, 1, 3), (10, 3, 2), (30, 3, 3)]
