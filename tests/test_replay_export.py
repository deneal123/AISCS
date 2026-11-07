import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.stimulation.replay_export import (
    export_reference_replay,
    load_verified_reference_replay,
)


def replay():
    return {'mapping': {'body_id': '42'}, 'selected_spikes': {'11': [2.]},
            'spikes_after_replay_window': 0, 'connectome_sha256': 'a' * 64,
            'provenance': {'configuration': {'duration_ms': 3.}},
            'replay': {'events': [], 'event_sources': []},
            'recording_configuration': {'electrode_um': [0., 1., 2.]},
            'interpretation': 'one-way replay', 'solution': {'time_ms': [0., 1., 2.]},
            'channel': {'neural_uv': [1., 2., 3.], 'stimulus_artifact_uv': [1., 0., -1.],
                        'total_uv': [2., 2., 2.]}}


def test_export_has_verified_manifest_and_does_not_overwrite(tmp_path):
    result = export_reference_replay(replay(), tmp_path)
    for item in result['files']:
        raw = (tmp_path / item['name']).read_bytes()
        assert len(raw) == item['bytes']
        assert hashlib.sha256(raw).hexdigest() == item['sha256']
    evidence = json.loads((tmp_path / 'replay-evidence.json').read_bytes())
    assert evidence['mapping']['body_id'] == '42'
    with np.load(tmp_path / 'replay-signal.npz') as values:
        np.testing.assert_array_equal(values['total_uv'], [2., 2., 2.])
    loaded = load_verified_reference_replay(tmp_path)
    np.testing.assert_array_equal(loaded['traces']['total_uv'], [2., 2., 2.])
    before = (tmp_path / 'replay-manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        export_reference_replay(replay(), tmp_path)
    assert (tmp_path / 'replay-manifest.json').read_bytes() == before


def test_modified_artifact_is_rejected(tmp_path):
    export_reference_replay(replay(), tmp_path)
    path = tmp_path / 'replay-evidence.json'
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"body_id":"42"', b'"body_id":"43"'))
    assert len(path.read_bytes()) == len(original)
    with pytest.raises(ValueError, match='checksum mismatch'):
        load_verified_reference_replay(tmp_path)


def test_invalid_trace_never_publishes_manifest(tmp_path):
    data = replay()
    data['channel']['total_uv'][1] = float('nan')
    with pytest.raises(ValueError, match='Invalid replay traces'):
        export_reference_replay(data, tmp_path)
    assert not (tmp_path / 'replay-manifest.json').exists()
