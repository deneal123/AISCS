import numpy as np
import pytest

from service.application.feedback.windowed_outputs import (
    WindowedFeedbackOutputs,
    solve_checked_windowed_feedback,
    solve_windowed_feedback,
)
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


def collector():
    geometry = {'edge_node_ids': np.array([7]), 'starts_um': np.array([[0., 0., 0.]]),
                'ends_um': np.array([[2., 0., 0.]]), 'midpoints_um': np.array([[1., 0., 0.]]),
                'endpoint_radii_um': np.array([[.1, .1]])}
    proof = {'body_id': '10', 'morphology_sha256': 'a'}
    diagnostic = {'body_id': '10', 'morphology_sha256': 'a', 'threshold_mv': -20.,
                  'duration_ms': 2, 'candidates': [{'included_in_graph': True,
                      'result_segment_index': 0, 'child_node_id': 7, 'partner_id': '20',
                      'source_position_8nm': [1, 2, 3]}]}
    return WindowedFeedbackOutputs({10: geometry}, {10: proof}, {10: diagnostic},
        threshold_mv=-20., duration_ms=2, samples=5, electrode_um=[10., 0., 0.],
        reference_um=[20., 0., 0.], conductivity_s_m=.3, clearance_um=1.)


def test_windowed_feedback_collects_events_and_recording():
    obj = collector()
    voltage = np.array([[-65., -65., -10., -65., -65.]])
    currents = np.array([[1., 2., 3., 4., 5.]])
    for start, end in [(0, 2), (2, 5)]:
        obj.accept(start, end, [{'id': 10, 'voltage_mv': voltage[:, start:end],
                                 'membrane_current_na': currents[:, start:end]}])
    result = obj.finish([0., .5, 1., 1.5, 2.])
    assert result['sources'][10]['edge_events'] == [
        {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
    coefficient = 1000 * bipolar_potential_mv([[1., 0., 0.]], [10., 0., 0.],
                                               [20., 0., 0.], 1., .3, clearance_um=1.)
    np.testing.assert_allclose(result['neural_uv'], coefficient @ currents)


def test_failed_window_cannot_be_published():
    obj = collector()
    with pytest.raises(ValueError, match='currents'):
        obj.accept(0, 1, [{'id': 10, 'voltage_mv': [[-65.]],
                           'membrane_current_na': [[float('nan')]]}])
    with pytest.raises(ValueError, match='failed'):
        obj.finish([0., .5, 1., 1.5, 2.])


def test_reduced_window_collects_recording_and_selected_events():
    obj = collector()
    for start, end, voltage, signal in [(0, 2, [[-65., -65.]], [1., 2.]),
                                        (2, 5, [[-10., -65., -65.]], [3., 4., 5.])]:
        obj.accept_reduced(start, end, [{'id': 10, 'selected_voltage_mv': voltage,
                                         'neural_uv': signal}])
    result = obj.finish([0., .5, 1., 1.5, 2.])
    np.testing.assert_array_equal(result['neural_uv'], [1., 2., 3., 4., 5.])
    assert result['sources'][10]['edge_events'][0]['tick'] == 1


@pytest.mark.parametrize('time', [[0., .5, 1., 1., 2.], [0., .5, 1., 1.5, 3.],
                                  [0., .5, 1., 1.5, float('nan')]])
def test_windowed_feedback_rejects_invalid_time_grid(time):
    with pytest.raises(ValueError, match='time grid'):
        collector().finish(time)


def test_experimental_replay_collects_a_complete_group(monkeypatch):
    example = collector()
    digest = 'a' * 64
    example.provenance[10]['morphology_sha256'] = digest
    example.diagnostics[10]['morphology_sha256'] = digest
    cells = [{'id': 10, 'geometry': example.geometries[10], 'morphology_sha256': digest}]

    def solve(group, stimulus, table, *, window_sink, **kwargs):
        window_sink((0,), 0, 5, [{'id': 10, 'voltage_mv': [[-65., -65., -10., -65., -65.]],
                                  'membrane_current_na': [[1., 2., 3., 4., 5.]]}])
        return {'time_ms': np.array([0., .5, 1., 1.5, 2.]), 'table_clamped_cell_ids': []}

    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.window_batches.'
                        'solve_windowed_groups', solve)
    result = solve_windowed_feedback(cells, example.provenance, example.diagnostics,
        [0.] * 5, None, threshold_mv=-20., duration_ms=2, electrode_um=[10., 0., 0.],
        reference_um=[20., 0., 0.], conductivity_s_m=.3, clearance_um=1., max_cells=2,
        output_budget_bytes=1000, window_steps=2, max_padding_ratio=2, dt_ms=.5)
    assert result['sources'][10]['edge_events'][0]['target_id'] == 20
    assert len(result['neural_uv']) == 5
    cells[0]['morphology_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='identity'):
        solve_windowed_feedback(cells, example.provenance, example.diagnostics,
            [0.] * 5, None, threshold_mv=-20., duration_ms=2, electrode_um=[10., 0., 0.],
            reference_um=[20., 0., 0.], conductivity_s_m=.3, clearance_um=1., max_cells=2,
            output_budget_bytes=1000, window_steps=2, max_padding_ratio=2, dt_ms=.5)


def test_checked_replay_rejects_stimulus_provenance_before_solving(monkeypatch):
    from service.domain.pulse_train import pulse_train
    from service.infrastructure.stimulation.experimental_gpu import recording_adapter
    from service.infrastructure.stimulation.experimental_gpu.waveform import kernel_midpoint_samples

    config = {'source_um': [0., 0., 0.], 'return_um': [20., 0., 0.], 'current_na': 1.,
              'conductivity_s_m': .3, 'clearance_um': .1, 'pulse_start_ms': .025,
              'pulse_end_ms': .075, 'rise_time_ms': 0., 'interphase_gap_ms': 0.,
              'pulse_shape': 'monophasic', 'duration_ms': .1, 'dt_ms': .025}
    times, levels = pulse_train(start_ms=.025, end_ms=.075, rise_ms=0., interphase_gap_ms=0.,
                                shape='monophasic', duration_ms=.1, count=1, interval_ms=None)
    stimulus = kernel_midpoint_samples(times, levels, dt_ms=.025, steps=4)
    cell = {'id': 1, 'events': [], 'field_current_na': [0.],
            'geometry': {'midpoints_um': [[10., 2., 0.]], 'junctions': [[(0, 1.)], [(0, 1.)]]}}
    proof = {1: {'configuration': {**config, 'synaptic_events': []}}}
    calls, artifact_calls = [], []
    original_artifact = recording_adapter.attach_windowed_artifact

    def count_artifact(*args, **kwargs):
        artifact_calls.append(True)
        return original_artifact(*args, **kwargs)

    monkeypatch.setattr(recording_adapter, 'attach_windowed_artifact', count_artifact)

    def fake_solve(*args, **kwargs):
        calls.append(True)
        return {'time_ms': np.arange(5) * .025, 'neural_uv': np.ones(5), 'sources': {1: {}}}

    monkeypatch.setattr('service.application.feedback.windowed_outputs.solve_windowed_feedback',
                        fake_solve)
    kwargs = {'duration_ms': .1, 'dt_ms': .025, 'conductivity_s_m': .3, 'clearance_um': .1,
              'electrode_um': [5., 5., 0.], 'reference_um': [15., 3., 0.]}
    result = solve_checked_windowed_feedback([cell], proof, {}, stimulus, None,
                                              stimulation_config=config, **kwargs)
    assert len(result['total_uv']) == 5 and len(calls) == 1
    assert len(artifact_calls) == 1
    proof[1]['configuration']['current_na'] = 2.
    with pytest.raises(ValueError, match='provenance'):
        solve_checked_windowed_feedback([cell], proof, {}, stimulus, None,
                                        stimulation_config=config, **kwargs)
    assert len(calls) == 1
