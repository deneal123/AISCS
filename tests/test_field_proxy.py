from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.field_proxy import descriptor_from_rows, run_field_proxy


def graph():
    return SimpleNamespace(size=2, ids=np.array([10, 20], np.int64), ptr=np.array([0, 0, 0], np.int64),
                           posts=np.array([], np.int32), counts=np.array([], np.int32),
                           signs=np.array([1, -1], np.int8))


def test_field_proxy_uses_signed_drive_and_seeded_control():
    kwargs = dict(descriptor=[1., -1.], waveform=[1.] * 10, gain=200., seed=7)
    active = run_field_proxy(graph(), **kwargs)
    repeat = run_field_proxy(graph(), **kwargs)
    control = run_field_proxy(graph(), **{**kwargs, 'waveform': [0.] * 10})
    assert np.array_equal(active['spike_neurons'], repeat['spike_neurons'])
    assert active['counts'][0] > 0 and active['counts'][1] == 0
    assert control['counts'].sum() == 0
    assert active['final_voltage_relative_mv'][1] < control['final_voltage_relative_mv'][1]


def test_progress_counts_completed_model_ticks_without_changing_results():
    kwargs = dict(descriptor=[1., -1.], waveform=[1.] * 101, gain=20., seed=7)
    events = []
    tracked = run_field_proxy(graph(), **kwargs,
                              progress=lambda done, total: events.append((done, total)))
    reference = run_field_proxy(graph(), **kwargs)
    np.testing.assert_array_equal(tracked['spike_neurons'], reference['spike_neurons'])
    np.testing.assert_array_equal(tracked['spike_times_ms'], reference['spike_times_ms'])
    np.testing.assert_array_equal(tracked['final_voltage_relative_mv'],
                                  reference['final_voltage_relative_mv'])
    assert events[0] == (0, 101) and events[-1] == (101, 101)
    assert len(events) <= 22 and all(total == 101 for _, total in events)
    assert all(a[0] < b[0] for a, b in zip(events, events[1:], strict=False))


@pytest.mark.parametrize('changes', [
    {'descriptor': [float('nan'), 0.]}, {'descriptor': [1.]},
    {'waveform': [float('inf')]}, {'gain': float('nan')}, {'seed': True},
])
def test_rejects_incomplete_or_invalid_inputs(changes):
    args = dict(descriptor=[1., 0.], waveform=[1.], gain=1., seed=1)
    with pytest.raises(ValueError):
        run_field_proxy(graph(), **{**args, **changes})


def test_field_rows_preserve_order_sign_and_reject_missing_values():
    rows = [{'body_id': '10', 'status': 'ok', 'max_abs_curvature_signed_mv_per_um2': -.2},
            {'body_id': '11', 'status': 'ok', 'max_abs_curvature_signed_mv_per_um2': .1}]
    assert np.allclose(descriptor_from_rows([10, 11], iter(rows)), [-.2, .1])
    partial = [rows[0], {**rows[1], 'status': 'partial_geometry'}]
    assert np.allclose(descriptor_from_rows([10, 11], iter(partial),
                                           allow_partial_geometry=True), [-.2, .1])
    for bad in (rows[:1], rows[::-1], [rows[0], {**rows[1], 'status': 'partial_geometry'}],
                [rows[0], {**rows[1], 'max_abs_curvature_signed_mv_per_um2': None}]):
        with pytest.raises(ValueError):
            descriptor_from_rows([10, 11], iter(bad))


def test_sparse_delta_matches_independent_control_and_reports_overflow(monkeypatch):
    kwargs = dict(descriptor=[1., -1.], waveform=[0., 1., 1., 0.], gain=20., seed=7)
    active = run_field_proxy(graph(), **kwargs, capture_sparse_delta=True)
    control = run_field_proxy(graph(), **{**kwargs, 'waveform': [0.] * 4})
    np.testing.assert_array_equal(active['control_spike_neurons'], control['spike_neurons'])
    np.testing.assert_array_equal(active['control_spike_times_ms'], control['spike_times_ms'])
    np.testing.assert_array_equal(active['control_counts'], control['counts'])
    sparse = active['sparse_delta']
    assert sparse['status'] == 'recorded' and len(sparse['offsets']) == 6
    start, end = sparse['offsets'][-2:]
    dense = np.zeros(2, np.float32)
    dense[sparse['indices'][start:end]] = sparse['values'][start:end]
    np.testing.assert_array_equal(
        dense, active['final_voltage_relative_mv'] - control['final_voltage_relative_mv'])
    monkeypatch.setattr('service.infrastructure.connectome.field_proxy.MAX_TARGET_RESPONSE_VALUES', 0)
    overflow = run_field_proxy(graph(), **kwargs, capture_sparse_delta=True)
    assert overflow['sparse_delta'] == {'status': 'limit_exceeded'}
    assert overflow['target_response']['time_ms'].tolist() == [0, 1, 2, 3, 4]
    np.testing.assert_array_equal(overflow['target_response']['active_relative_mv'][-1]
                                  - overflow['target_response']['control_relative_mv'][-1], dense)
