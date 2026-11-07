from types import SimpleNamespace

import numpy as np

from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.stimulation import synaptic_replay
from service.infrastructure.stimulation.verified_spike_index import VerifiedSpikeIndex


def test_cached_and_standard_incoming_replay_match(monkeypatch):
    graph = SimpleNamespace(ids=np.array([1, 2, 3]), provenance={'manifest_sha256': 'graph'})
    binary, description, sha = encode_forced_spikes(graph, {
        'spike_neurons': np.array([0, 1, 0]), 'spike_times_ms': np.array([1., 2., 4.]),
        'metadata': {'graph': graph.provenance, 'duration_ms': 10}})
    mapping = {'body_id': '3', 'candidates': [{'partner_id': '1'}, {'partner_id': '2'}]}
    monkeypatch.setattr('service.infrastructure.connectome.synapse_morphology.registered_incoming_candidates_single_pass',
                        lambda *_args, **_kwargs: mapping)
    monkeypatch.setattr(synaptic_replay, 'execute_reference_replay',
                        lambda _mapping, spikes, *_args, **_kwargs: {'spikes': spikes})
    params = {'binary': binary, 'description': description, 'expected_sha256': sha,
              'schedule_parameters': {'duration_ms': 10, 'delay_ms': 2},
              'simulation_parameters': {}, 'electrode_um': [0, 1, 2],
              'reference_um': [2, 3, 4], 'source_model': 'pointsource'}
    index = VerifiedSpikeIndex(binary, description, sha, graph.ids, 'graph')
    ordinary = synaptic_replay.execute_all_incoming_replay(None, graph, 3, [], **params)
    cached = synaptic_replay._execute_preverified_incoming_replay(
        None, graph, 3, [], **params, spike_index=index, active=index.active_before(10, 2))
    assert cached == ordinary
