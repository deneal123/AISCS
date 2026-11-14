import hashlib
import json

import numpy as np
import pytest

from service.application.population.bulk_recording_export import (
    export_bulk_recording,
    read_bulk_recording,
)


def test_atomic_export_preserves_data_and_independent_interpretation(tmp_path):
    destination = tmp_path / 'recording.npz'
    result = {'time_ms': np.array([0., .05]), 'neural_uv': np.array([1., -2.]),
              'cells': 2, 'interpretation': 'independent cells; no network feedback',
              'replacement_receipts': [{'body_id': 2, 'transformation': {'source_sha256': 'a'}}]}
    receipt = export_bulk_recording(destination, result, graph_sha256='a' * 64,
                                    configuration_sha256='b' * 64)
    assert receipt['sha256'] == hashlib.sha256(destination.read_bytes()).hexdigest()
    read_options = dict(sha256=receipt['sha256'], graph_sha256='a' * 64,
                        configuration_sha256='b' * 64)
    restored = read_bulk_recording(destination, **read_options)
    np.testing.assert_array_equal(restored['neural_uv'], result['neural_uv'])
    assert restored['replacement_receipts'] == result['replacement_receipts']
    with pytest.raises(ValueError, match='provenance'):
        read_bulk_recording(destination, **{**read_options, 'graph_sha256': 'c' * 64})
    with pytest.raises(ValueError, match='digest'):
        read_bulk_recording(destination, **{**read_options, 'sha256': '0' * 64})
    with np.load(destination, allow_pickle=False) as data:
        np.testing.assert_array_equal(data['neural_uv'], result['neural_uv'])
        assert str(data['graph_sha256']) == 'a' * 64
        assert 'no network feedback' in str(data['interpretation'])
        assert json.loads(str(data['replacement_receipts_json'])) == result['replacement_receipts']
    with pytest.raises(ValueError, match='samples'):
        export_bulk_recording(destination, {**result, 'neural_uv': [float('nan'), 0]},
                              graph_sha256='a' * 64, configuration_sha256='b' * 64)
    assert receipt['sha256'] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert list(tmp_path.iterdir()) == [destination]
