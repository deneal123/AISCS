import hashlib

import numpy as np
import pytest

from service.application.feedback import paired_uniform


def test_paired_replay_uses_shared_transform_and_publishes_atomically(tmp_path, monkeypatch):
    prepared = {'nseg_by_body': {7: 3}, 'restart_required': True, 'audit': {'verified': True},
        'conditions': {name: {'schedule': {'name': name}, 'sha256': name,
                              'original_sha256': name}
                       for name in ('control', 'stimulated')}}
    monkeypatch.setattr(paired_uniform, 'prepare_uniform_feedback_replays',
                        lambda *_a, **_k: prepared)
    marker = object()
    monkeypatch.setattr(paired_uniform, 'uniform_cell_transform', lambda *_a, **_k: marker)
    calls = []

    def replay(_metadata, signal, _table, **kwargs):
        assert kwargs['cell_transform'] is marker
        calls.append((kwargs['schedule']['name'], np.asarray(signal).tolist()))
        kwargs['event_path'].write_text('events', encoding='utf8')
        return {'cells': 1, 'neural_uv': np.zeros(len(signal)),
                'event_sha256': hashlib.sha256(b'events').hexdigest()}

    monkeypatch.setattr(paired_uniform, 'replay_verified_feedback_to_archive', replay)
    options = dict(conditions={}, index=None, directories=[], policy={}, morphology_sha256={},
                   metadata_factory=lambda cells: cells,
                   replay_options={'params': object(), 'time_ms': [0., 1., 2.]})
    destination = tmp_path / 'result'
    result = paired_uniform.replay_paired_uniform({}, [0., 1., 0.], None,
        output_directory=destination, **options)
    assert calls == [('control', [0., 0., 0.]), ('stimulated', [0., 1., 0.])]
    assert sorted(path.name for path in destination.iterdir()) == [
        'control.jsonl', 'grid-audit.json', 'manifest.json', 'signals.npz', 'stimulated.jsonl']
    assert result['grid'] == {7: 3}

    def corrupt(*_a, **kwargs):
        kwargs['event_path'].write_text('changed', encoding='utf8')
        return {'cells': 1, 'neural_uv': np.zeros(3), 'event_sha256': '0' * 64}

    monkeypatch.setattr(paired_uniform, 'replay_verified_feedback_to_archive', corrupt)
    with pytest.raises(ValueError, match='digest mismatch'):
        paired_uniform.replay_paired_uniform({}, [0., 1., 0.], None,
                                            output_directory=tmp_path / 'corrupt', **options)
    assert not (tmp_path / 'corrupt').exists()

    def fail(*_a, **kwargs):
        kwargs['event_path'].write_text('partial', encoding='utf8')
        raise RuntimeError('replay failed')

    monkeypatch.setattr(paired_uniform, 'replay_verified_feedback_to_archive', fail)
    failed = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='replay failed'):
        paired_uniform.replay_paired_uniform({}, [0., 1.], None,
                                            output_directory=failed, **options)
    assert not failed.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ['result']
