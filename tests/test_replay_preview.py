import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.stimulation.recording.replay_export import export_reference_replay
from service.infrastructure.stimulation.recording.replay_preview import (
    export_replay_preview,
    replay_preview,
)
from tests.test_replay_export import replay


def test_preview_preserves_narrow_peaks_and_endpoints(tmp_path):
    data = replay()
    n = 1001
    signal = np.zeros(n)
    signal[311], signal[312] = 7., -5.
    data['solution']['time_ms'] = np.arange(n).tolist()
    data['channel'] = {'neural_uv': signal.tolist(), 'stimulus_artifact_uv': np.zeros(n).tolist(),
                       'total_uv': signal.tolist()}
    export_reference_replay(data, tmp_path)
    result = replay_preview(tmp_path, bins=10)
    assert 7. in result['signal_uv'] and -5. in result['signal_uv']
    assert result['time_ms'][0] == 0. and result['time_ms'][-1] == 1000.
    assert result['time_ms'] == sorted(result['time_ms'])
    assert result['shown_samples'] <= 22 and result['original_samples'] == n
    assert 'not a full-CNS' in result['limitations'][0]


def test_preview_rejects_invalid_resolution(tmp_path):
    with pytest.raises(ValueError, match='positive'):
        replay_preview(tmp_path, bins=True)


def test_export_is_hashed_and_never_overwrites(tmp_path):
    export_reference_replay(replay(), tmp_path)
    item = export_replay_preview(tmp_path)
    raw = (tmp_path / item['name']).read_bytes()
    assert item['bytes'] == len(raw)
    assert item['sha256'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw)['signal_scope'].startswith('neural contribution of one')
    with pytest.raises(FileExistsError):
        export_replay_preview(tmp_path)
    assert (tmp_path / item['name']).read_bytes() == raw


def test_export_rejects_corrupt_source_before_writing(tmp_path):
    export_reference_replay(replay(), tmp_path)
    (tmp_path / 'replay-signal.npz').write_bytes(b'bad')
    with pytest.raises(ValueError, match='checksum'):
        export_replay_preview(tmp_path)
    assert not (tmp_path / 'replay-preview.json').exists()
