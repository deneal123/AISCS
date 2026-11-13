import os

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu import batch_solver
from service.infrastructure.stimulation.experimental_gpu.batch_solver import (
    _final_segment_voltages,
    solve_prepared_batch,
)
from service.infrastructure.stimulation.experimental_gpu.packing import pack_trees


@pytest.fixture
def inputs():
    cell = {
        "id": 1,
        "geometry": {
            "parents": [-1, 0],
            "conductances": [0.0, 0.5],
            "segment_nodes": [1],
            "area": [1.0],
            "grid": [(2, 0, 1)],
        },
        "field_current_na": [0.0],
        "events": [],
        "initial_voltage_mv": -65.0,
        "initial_gates": [0.5, 0.5, 0.5],
    }
    return {
        "cells": [cell],
        "stimulus_midpoint": [0.0, 1.0, 1.0],
        "rate_table": np.tile([0.5, 1.0, 0.5, 1.0, 0.5, 1.0], (201, 1)),
        "output_budget_bytes": 1024,
    }


def test_rejects_insufficient_output_budget_before_cuda(inputs):
    inputs["output_budget_bytes"] = 1
    with pytest.raises(ValueError, match="budget"):
        solve_prepared_batch(**inputs)


def test_rejects_duplicate_ids_before_cuda(inputs):
    inputs["cells"].append(inputs["cells"][0])
    with pytest.raises(ValueError, match="unique"):
        solve_prepared_batch(**inputs)


def test_rejects_invalid_timing_callback_before_cuda(inputs):
    with pytest.raises(ValueError, match='Invalid GPU batch'):
        solve_prepared_batch(**inputs, timing_sink=True)


@pytest.mark.parametrize('coefficients,indices', [({1: [1.]}, {1: [1]}),
                                                    ({1: [float('nan')]}, {1: [0]}),
                                                    ({2: [1.]}, {1: [0]})])
def test_rejects_invalid_device_recording_selection(inputs, coefficients, indices):
    with pytest.raises(ValueError, match='recording selection'):
        solve_prepared_batch(**inputs, device_window_sink=lambda *args: None,
                             recording_coefficients=coefficients, selected_indices=indices)


def test_rejects_endpoint_before_cuda(inputs):
    inputs["cells"][0]["events"] = [
        {
            "child_node_id": 2,
            "position": 1.0,
            "time_ms": 0.025,
            "weight_us": 0.1,
            "tau1_ms": 0.1,
            "tau2_ms": 1.0,
            "reversal_mv": 0.0,
        }
    ]
    with pytest.raises(ValueError, match="Unsupported event"):
        solve_prepared_batch(**inputs)


def test_final_voltage_ignores_padding_but_rejects_invalid_segments():
    packed = pack_trees([([-1, 0, 1], [0., 1., 1.], [1, 2]),
                         ([-1, 0], [0., 1.], [1])])
    final = np.array([[0., 0.], [-65., -60.], [-64., np.nan]])
    values = _final_segment_voltages(final, packed, 2)
    np.testing.assert_array_equal(values[1], [-60.])
    final[1, 1] = np.nan
    with pytest.raises(ValueError, match='Non-finite'):
        _final_segment_voltages(final, packed, 2)


@pytest.mark.parametrize('different_state', ['voltage', 'gates'])
@pytest.mark.parametrize('prepacked', [False, True])
def test_mixed_initial_states_fall_back_to_generic_packing(inputs, monkeypatch,
                                                           different_state, prepacked):
    first = inputs['cells'][0]
    second = dict(first, id=2)
    if different_state == 'voltage':
        second['initial_voltage_mv'] = -60.0
    else:
        second['initial_gates'] = [0.4, 0.5, 0.5]
    inputs['cells'].append(second)

    def generic_packing(trees):
        assert len(trees) == 2
        raise RuntimeError('generic path reached')

    monkeypatch.setattr(batch_solver, 'pack_trees', generic_packing)
    options = {'cell_major_packed': (object(), None, None)} if prepacked else {}
    with pytest.raises(RuntimeError, match='generic path reached'):
        solve_prepared_batch(**inputs, cell_major=True, record_traces=False, **options)


@pytest.mark.skipif(os.environ.get('NUMBA_ENABLE_CUDASIM') != '1',
                    reason='Explicit CPU CUDA-simulator check')
def test_mixed_initial_states_match_generic_solver_in_cuda_simulator(inputs):
    first = inputs['cells'][0]
    inputs['cells'].append(dict(first, id=2, initial_voltage_mv=-60.0,
                                initial_gates=[0.4, 0.5, 0.5]))
    inputs['output_budget_bytes'] = 1024 * 1024
    reference = solve_prepared_batch(**inputs, record_traces=False)
    fallback = solve_prepared_batch(**inputs, cell_major=True, record_traces=False)
    for expected, actual in zip(reference['final_voltage_mv'], fallback['final_voltage_mv'],
                                strict=True):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.skipif(os.environ.get('NUMBA_ENABLE_CUDASIM') != '1',
                    reason='Explicit CPU CUDA-simulator check')
def test_final_only_matches_recorded_final_in_cuda_simulator(inputs):
    first = inputs['cells'][0]
    first['field_current_na'] = [0.012]
    inputs['cells'].append(dict(first, id=2, initial_voltage_mv=-60.0,
                                field_current_na=[-0.008]))
    inputs['output_budget_bytes'] = 1024 * 1024
    recorded = solve_prepared_batch(**inputs, record_traces=True)
    final_only = solve_prepared_batch(**inputs, record_traces=False)
    for expected, actual in zip(recorded['cells'], final_only['final_voltage_mv'], strict=True):
        np.testing.assert_array_equal(actual, expected['final_voltage_mv'])
    assert final_only['table_clamped_cell_ids'] == recorded['table_clamped_cell_ids']
