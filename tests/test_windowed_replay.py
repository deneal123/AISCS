import numpy as np
import pytest

from service.application.feedback.windowed_replay import replay_windowed_sources


def test_windowed_replay_aggregates_neural_and_artifact_once(monkeypatch):
    simulation = {'dt_ms': .025, 'duration_ms': .1, 'pulse_start_ms': .025,
        'pulse_end_ms': .075, 'rise_time_ms': 0., 'interphase_gap_ms': 0.,
        'pulse_shape': 'monophasic', 'source_um': [0., 0., 0.], 'return_um': [1., 0., 0.],
        'current_na': 1., 'conductivity_s_m': .3, 'clearance_um': 1.}
    requests = [{'id': 1}, {'id': 2}]
    monkeypatch.setattr('service.application.feedback.windowed_replay.prepare_windowed_sources',
        lambda group, *args, **kwargs: {'cells': group, 'provenance': {}, 'hh_table': None})

    observed = []

    def solve(cells, *args, **kwargs):
        observed.append(kwargs)
        body = cells[0]['id']
        return {'time_ms': np.arange(5) * .025, 'neural_uv': np.full(5, body),
                'stimulus_fraction': np.zeros(5), 'stimulus_artifact_uv': np.ones(5),
                'sources': {body: {}}, 'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.application.feedback.windowed_replay.'
                        'solve_checked_windowed_feedback', solve)
    options = dict(electrode_um=[1., 1., 0.], reference_um=[2., 1., 0.],
        threshold_mv=-20., duration_ms=.1, max_source_distance_um=None, max_cells=1,
        output_budget_bytes=1000, window_steps=2)
    result = replay_windowed_sources(requests, [], simulation, {1: {}, 2: {}}, **options)
    np.testing.assert_array_equal(result['recording']['neural_uv'], np.full(5, 3))
    np.testing.assert_array_equal(result['recording']['total_uv'], np.full(5, 4))
    assert list(result['sources']) == [1, 2]
    replay_windowed_sources(requests, [], simulation, {1: {}, 2: {}},
                            device_reduction=True, cell_major=True, **options)
    assert all(item['cell_major'] is True for item in observed[2:])
    with pytest.raises(ValueError, match='window replay request'):
        replay_windowed_sources(requests, [], simulation, {1: {}, 2: {}},
                                cell_major=True, **options)
    with pytest.raises(ValueError, match='pulse train'):
        replay_windowed_sources(requests, [], {**simulation, 'pulse_count': 0},
                                {1: {}, 2: {}}, **options)
