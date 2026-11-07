from pathlib import Path
from types import SimpleNamespace

import pytest

from service.application.replay.verified_population_target import replay_verified_population_target


def test_verified_replay_uses_archive_sources_and_rejects_overlap(monkeypatch):
    module = 'service.application.replay.verified_population_target.'
    config = SimpleNamespace(source_ids=[10, 11], max_distance_um=2,
        digest=lambda: 'a' * 64, execution_parameters=lambda: {
            'simulation_parameters': {}, 'electrode_um': [0, 0, 0],
            'reference_um': [1, 0, 0], 'source_model': 'pointsource'})
    monkeypatch.setattr(module + 'FragmentPopulationConfig', SimpleNamespace(
        model_validate=lambda _value: config))
    verified = {'metadata': {'configuration': {}, 'recording': {'cells': 2},
                             'diagnostics': [{'body_id': '10'}, {'body_id': '11'}]},
                'arrays': {'time_ms': [0, 1], 'neural_uv': [0, 1],
                           'stimulus_artifact_uv': [0, 0], 'total_uv': [0, 1]},
                'manifest': {'files': []}}
    monkeypatch.setattr(module + 'load_verified_fragment_population', lambda *_: verified)
    calls = []
    monkeypatch.setattr(module + 'replay_fragment_target_population',
                        lambda diagnostics, *_a, **kw: calls.append((diagnostics, kw)) or {})
    monkeypatch.setattr(module + 'combine_fragment_target_recording',
                        lambda _source, _replay, **kw: {'source_ids': kw['source_ids']})
    kwargs = {'target_id': 20, 'source_ids': [11], 'schedule_parameters': [{}],
              'max_target_distance_um': 2, 'max_events': 10}
    result = replay_verified_population_target(Path('.'), None, None, [], **kwargs)
    assert calls[0][0] == [{'body_id': '11'}]
    assert calls[0][1]['max_source_distance_um'] == 2
    assert result['recording']['source_ids'] == [10, 11]
    with pytest.raises(ValueError, match='conflict'):
        replay_verified_population_target(Path('.'), None, None, [], **{**kwargs, 'target_id': 10})
    with pytest.raises(ValueError, match='conflict'):
        replay_verified_population_target(Path('.'), None, None, [],
                                          **{**kwargs, 'source_ids': [12]})
