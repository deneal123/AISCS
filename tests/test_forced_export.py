import numpy as np
import pytest

from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.connectome.forced_network import run_forced_network
from service.infrastructure.stimulation.synaptic_replay import read_verified_spikes
from tests.test_forced_network import graph


def test_encoded_forced_events_round_trip_into_checked_replay():
    model = graph()
    result = run_forced_network(model, seed=1, duration_ms=6,
                                forced_cell_ids=[10], events={10: [1]})
    binary, description, digest = encode_forced_spikes(model, result)
    selected = read_verified_spikes(binary, description, digest, model.ids,
                                    model.provenance['manifest_sha256'], [10, 20, 30])
    assert selected == {'10': [1.], '20': [3.], '30': [5.]}
    with pytest.raises(ValueError, match='checksum'):
        read_verified_spikes(binary + b'x', description, digest, model.ids,
                             model.provenance['manifest_sha256'], [10])


@pytest.mark.parametrize('change', ['graph', 'index', 'time'])
def test_export_rejects_incompatible_graph_and_bad_events(change):
    model = graph()
    result = run_forced_network(model, seed=1, duration_ms=6,
                                forced_cell_ids=[10], events={10: [1]})
    if change == 'graph':
        result['metadata']['graph'] = {'manifest_sha256': 'other'}
    elif change == 'index':
        result['spike_neurons'] = np.array([4], dtype=np.int32)
        result['spike_times_ms'] = np.array([1.], dtype=np.float32)
    else:
        result['spike_times_ms'][0] = 7
    with pytest.raises(ValueError):
        encode_forced_spikes(model, result)
