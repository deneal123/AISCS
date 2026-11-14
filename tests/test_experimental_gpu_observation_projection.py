import os

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.observation_projection import (
    nodal_recording_projection,
)


def _direct(parent, conductance, segments, coefficients, field, voltage, stimulus):
    total = 0.0
    for index, node in enumerate(segments):
        current = field[index] * stimulus
        if node > 0:
            current -= conductance[node] * (voltage[node] - voltage[parent[node]])
        for child in range(1, len(parent)):
            if parent[child] == node:
                current += conductance[child] * (voltage[child] - voltage[node])
        total += coefficients[index] * current
    return total


def test_projection_matches_original_current_equation_for_branched_trees():
    rng = np.random.default_rng(41)
    for size in (1, 2, 10, 80):
        parent = np.array([-1, *(rng.integers(0, i) for i in range(1, size))])
        conductance = rng.uniform(0.01, 2, size)
        segments = rng.choice(size, max(1, size // 2), replace=False)
        coefficients = rng.normal(size=len(segments))
        field = rng.normal(size=len(segments))
        weights, factor = nodal_recording_projection(
            parent, conductance, segments, coefficients, field)
        for stimulus in (0.0, -0.3, 0.7):
            voltage = rng.normal(-65.0, 2, size)
            expected = _direct(parent, conductance, segments, coefficients,
                               field, voltage, stimulus)
            np.testing.assert_allclose(weights @ voltage + factor * stimulus, expected,
                                       rtol=1e-11, atol=1e-11)


def test_common_mode_voltage_does_not_contribute():
    weights, factor = nodal_recording_projection(
        [-1, 0, 1, 1], [0, 1, 2, 3], [0, 2, 3], [1, -1, 4], [0, 0, 0])
    assert factor == 0
    assert abs(weights @ np.full(4, -65.0)) < 1e-12


def test_centered_projection_matches_direct_currents_with_large_common_voltage():
    parent = np.array([-1, 0, 0, 1, 1, 3])
    conductance = np.array([0., .2, .4, .1, .3, .8])
    segments = np.array([1, 2, 4, 5])
    coefficients = np.array([.8, -1.1, .2, 1.4])
    field = np.array([.01, -.02, .03, .04])
    voltage = np.array([-65., -64.99, -65.03, -65.01, -65.04, -64.98])
    weights, factor = nodal_recording_projection(parent, conductance, segments,
                                                 coefficients, field)
    for stimulus in (0., 1.):
        reference = _direct(parent, conductance, segments, coefficients, field,
                            voltage, stimulus)
        centered = weights @ (voltage - voltage[0]) + factor * stimulus
        np.testing.assert_allclose(centered, reference, atol=1e-14, rtol=1e-12)


@pytest.mark.skipif(os.environ.get('NUMBA_ENABLE_CUDASIM') != '1'
                    and os.environ.get('AISCS_TEST_CUDA') != '1',
                    reason='Explicit CUDA or CPU CUDA-simulator check')
def test_projection_matches_recorded_currents_in_cuda_simulator():
    from service.infrastructure.stimulation.experimental_gpu.batch_solver import (
        solve_prepared_batch,
    )

    parents = [-1, 0, 0]
    conductance = [0., 0.5, 0.8]
    segments = [1, 2]
    field = [0.012, -0.008]
    coefficients = np.array([1.7, -0.9])
    stimulus = np.array([0., 1., 0.5, 0.])
    cell = {'id': 1, 'geometry': {'parents': parents, 'conductances': conductance,
            'segment_nodes': segments, 'area': [1., 1.], 'grid': [(1, 0, 1), (2, 0, 1)]},
            'field_current_na': field, 'events': [], 'initial_voltage_mv': -65.,
            'initial_gates': [0.5, 0.5, 0.5]}
    table = np.tile([0.5, 1., 0.5, 1., 0.5, 1.], (201, 1))
    recorded = solve_prepared_batch([cell], stimulus, table, output_budget_bytes=1024 * 1024)
    voltages = recorded['cells'][0]['voltage_mv']
    currents = recorded['cells'][0]['membrane_current_na']
    # The root has no membrane or drive; its voltage is the conductance-weighted
    # mean of the two children at each solved step.
    root = (0.5 * voltages[0] + 0.8 * voltages[1]) / 1.3
    nodes = np.vstack((root, voltages))
    weights, factor = nodal_recording_projection(parents, conductance, segments,
                                                 coefficients, field)
    np.testing.assert_allclose(weights @ nodes + factor * stimulus, coefficients @ currents,
                               atol=1e-12, rtol=1e-10)


@pytest.mark.skipif(os.environ.get('NUMBA_ENABLE_CUDASIM') != '1'
                    and os.environ.get('AISCS_TEST_CUDA') != '1',
                    reason='Explicit CUDA or CPU CUDA-simulator check')
def test_device_projection_and_selected_nodes_in_cuda_simulator():
    from numba import cuda

    from service.infrastructure.stimulation.experimental_gpu.observation_kernel import (
        record_node_projection,
    )

    voltage = np.array([[-65., -64., -63., np.nan, np.nan],
                        [-60., -61., -62., -63., -64.]])
    weights = np.array([[0.1, -0.3, 0.2, np.nan, np.nan],
                        [0.5, -0.2, 0.7, -0.6, -0.4]])
    counts = np.array([3, 5], dtype=np.int64)
    factors = np.array([0.2, -0.8])
    selected_nodes = np.array([[2, 4], [0, 3]], dtype=np.int64)
    selected_counts = np.array([1, 2], dtype=np.int64)
    signal = cuda.to_device(np.full((2, 2), np.nan))
    chosen = cuda.to_device(np.full((2, 2, 2), np.nan))
    record_node_projection[2, 32](cuda.to_device(voltage), cuda.to_device(weights),
        cuda.to_device(counts), cuda.to_device(factors), 0.7,
        cuda.to_device(selected_nodes), cuda.to_device(selected_counts), 1, signal, chosen)
    result, selected = signal.copy_to_host(), chosen.copy_to_host()
    for cell, length in enumerate(counts):
        np.testing.assert_allclose(result[1, cell], weights[cell, :length] @ voltage[cell, :length]
                                   + factors[cell] * 0.7, rtol=1e-13, atol=1e-13)
        np.testing.assert_array_equal(selected[1, :selected_counts[cell], cell],
                                      voltage[cell, selected_nodes[:selected_counts[cell], cell]])
    assert np.isnan(result[0]).all()
    assert np.isnan(selected[1, 1, 0])


@pytest.mark.skipif(os.environ.get('NUMBA_ENABLE_CUDASIM') != '1'
                    and os.environ.get('AISCS_TEST_CUDA') != '1',
                    reason='Explicit CUDA or CPU CUDA-simulator check')
@pytest.mark.parametrize('with_events', [False, True])
@pytest.mark.parametrize('kernel', ['block', 'warp'])
def test_cell_major_reduced_windows_match_generic_in_cuda_simulator(with_events, kernel):
    if kernel == 'warp' and os.environ.get('NUMBA_ENABLE_CUDASIM') == '1':
        pytest.skip('CUDA simulator does not implement warp synchronization')
    from service.infrastructure.stimulation.experimental_gpu.batch_solver import (
        solve_prepared_batch,
    )

    cell = {'id': 1, 'geometry': {'parents': [-1, 0, 0],
            'conductances': [0., 0.5, 0.8], 'segment_nodes': [1, 2], 'area': [1., 1.],
            'grid': [(1, 0, 1), (2, 0, 1)]}, 'field_current_na': [0.012, -0.008],
            'events': [], 'initial_voltage_mv': -65., 'initial_gates': [0.5, 0.5, 0.5]}
    other = dict(cell, id=2, field_current_na=[-0.004, 0.006])
    if with_events:
        cell['events'] = [{'child_node_id': 1, 'position': 0.5, 'time_ms': .025,
                           'weight_us': .01, 'tau1_ms': .1, 'tau2_ms': 1.,
                           'reversal_mv': 0.}]
        other['events'] = [{'child_node_id': 2, 'position': 0.5, 'time_ms': .05,
                            'weight_us': .02, 'tau1_ms': .1, 'tau2_ms': 1.,
                            'reversal_mv': -80.}]
    table = np.tile([0.5, 1., 0.5, 1., 0.5, 1.], (201, 1))
    stimulus = [0., 1., 0.5, 0., 0.]
    coeff = {1: [1.7, -0.9], 2: [-0.3, 0.2]}
    selection = {1: [1, 0], 2: [0]}
    standard, accelerated = [], []

    def sink(target):
        def accept(start, end, rows):
            target.append((start, end, rows))
        return accept

    common = dict(cells=[cell, other], stimulus_midpoint=stimulus, rate_table=table,
                  output_budget_bytes=1024 * 1024, window_steps=2,
                  recording_coefficients=coeff, selected_indices=selection)
    reference = solve_prepared_batch(**common, device_window_sink=sink(standard))
    actual = solve_prepared_batch(**common, device_window_sink=sink(accelerated),
                                  cell_major=True,
                                  block_cell_segments=1 if kernel == 'block' else 10,
                                  cell_major_block_threads=32)
    assert [(a, b) for a, b, _ in standard] == [(0, 3), (3, 5)]
    assert [(a, b) for a, b, _ in accelerated] == [(0, 3), (3, 5)]
    for (_, _, expected), (_, _, result) in zip(standard, accelerated, strict=True):
        assert [row['id'] for row in result] == [1, 2]
        for left, right in zip(expected, result, strict=True):
            np.testing.assert_allclose(right['neural_uv'], left['neural_uv'], atol=1e-11)
            np.testing.assert_allclose(right['selected_voltage_mv'], left['selected_voltage_mv'],
                                       atol=1e-11)
    for left, right in zip(reference['final_voltage_mv'], actual['final_voltage_mv'], strict=True):
        np.testing.assert_allclose(right, left, atol=1e-11)


@pytest.mark.skipif(os.environ.get('AISCS_TEST_CUDA') != '1',
                    reason='Explicit physical CUDA check')
@pytest.mark.parametrize('warps', [2, 4, 8])
def test_fused_recording_handles_partial_multiwarp_blocks_on_gpu(warps):
    from service.infrastructure.stimulation.experimental_gpu.batch_solver import (
        solve_prepared_batch,
    )

    geometry = {'parents': [-1, 0, 0], 'conductances': [0., .5, .8],
                'segment_nodes': [1, 2], 'area': [1., 1.], 'grid': [(1, 0, 1), (2, 0, 1)]}
    cells = [{'id': body, 'geometry': geometry, 'field_current_na': [.001 * body, -.002],
              'events': [], 'initial_voltage_mv': -65., 'initial_gates': [.5, .5, .5]}
             for body in range(1, 6)]
    coeff = {body: [0.2 * body, -0.3] for body in range(1, 6)}
    selection = {body: [1, 0] if body % 2 else [0] for body in range(1, 6)}
    standard, fused = [], []

    def sink(target):
        def accept(start, end, rows):
            target.append((start, end, rows))
        return accept

    common = dict(cells=cells, stimulus_midpoint=[0., 1., .5, 0., 0.],
                  rate_table=np.tile([.5, 1., .5, 1., .5, 1.], (201, 1)),
                  output_budget_bytes=1024 * 1024, window_steps=2,
                  recording_coefficients=coeff, selected_indices=selection)
    solve_prepared_batch(**common, device_window_sink=sink(standard))
    solve_prepared_batch(**common, device_window_sink=sink(fused), cell_major=True,
                         cell_warps=warps)
    assert [(start, end) for start, end, _ in fused] == [(0, 3), (3, 5)]
    for (_, _, expected), (_, _, actual) in zip(standard, fused, strict=True):
        assert [row['id'] for row in actual] == list(range(1, 6))
        for left, right in zip(expected, actual, strict=True):
            np.testing.assert_allclose(right['neural_uv'], left['neural_uv'], atol=1e-11)
            np.testing.assert_allclose(right['selected_voltage_mv'], left['selected_voltage_mv'],
                                       atol=1e-11)


@pytest.mark.parametrize('parents,conductance,segments,coefficient,field', [
    ([-1, 2], [0, 1], [1], [1], [1]),
    ([-1, 0], [0, -1], [1], [1], [1]),
    ([-1, 0], [0, 1], [1, 1], [1, 2], [1, 1]),
    ([-1, 0], [0, 1], [1], [float('nan')], [1]),
    ([-1, 0], [0, 1], [1], [1, 2], [1]),
])
def test_invalid_projection_is_rejected(parents, conductance, segments, coefficient, field):
    with pytest.raises(ValueError, match='Invalid recording projection'):
        nodal_recording_projection(parents, conductance, segments, coefficient, field)
