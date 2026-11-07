import numpy as np
import pytest

from service.infrastructure.connectome.forced_export import (
    encode_forced_spikes,
    write_forced_spikes,
)
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


@pytest.mark.parametrize('empty', [False, True])
def test_streaming_export_matches_original_bytes_and_metadata(tmp_path, empty):
    model = graph()
    result = run_forced_network(model, seed=1, duration_ms=6,
                                forced_cell_ids=[10], events={10: [1]})
    if empty:
        result['spike_neurons'] = np.array([], dtype=np.int64)
        result['spike_times_ms'] = np.array([], dtype=np.float64)
    else:
        # Exercise non-contiguous arrays and conversions on every chunk.
        for name in ('spike_neurons', 'spike_times_ms'):
            result[name] = np.repeat(result[name], 2)[::2]
    binary, description, digest = encode_forced_spikes(model, result)
    path = tmp_path / 'events.bin'
    streamed_description, streamed_digest = write_forced_spikes(path, model, result, chunk_items=1)
    assert path.read_bytes() == binary
    assert (streamed_description, streamed_digest) == (description, digest)
    with pytest.raises(FileExistsError):
        write_forced_spikes(path, model, result)
    assert path.read_bytes() == binary


def test_streaming_export_removes_partial_file_on_write_error(tmp_path, monkeypatch):
    model = graph()
    result = run_forced_network(model, seed=1, duration_ms=6,
                                forced_cell_ids=[10], events={10: [1]})
    path = tmp_path / 'events.bin'
    real_open = type(path).open

    class BrokenStream:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, data):
            self.stream.write(data[:1])
            raise OSError('disk full')
        def close(self):
            self.stream.close()

    monkeypatch.setattr(type(path), 'open',
                        lambda p, *a, **kw: BrokenStream(real_open(p, *a, **kw)))
    with pytest.raises(OSError, match='disk full'):
        write_forced_spikes(path, model, result)
    assert not path.exists()


def test_validation_without_replay_partners_does_not_allocate_selection(monkeypatch):
    model = graph()
    result = run_forced_network(model, seed=1, duration_ms=6,
                                forced_cell_ids=[10], events={10: [1]})
    monkeypatch.setattr(np, 'isin', lambda *_args, **_kwargs: pytest.fail('unneeded selection'))
    binary, description, digest = encode_forced_spikes(model, result)
    assert binary and description['binary']['bytes'] == len(binary) and len(digest) == 64
