import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu import refined_population


def test_selected_grid_preserves_identity_and_captures_original(monkeypatch):
    params = SimpleNamespace(nseg=1, source_um=(0, 0, 0), return_um=(1, 0, 0),
        current_na=3, conductivity_s_m=.3, clearance_um=.1, axial_resistivity=100,
        capacitance=1)
    original = {'id': 7, 'morphology_sha256': 'a' * 64, 'initial_voltage_mv': -65.,
                'initial_gates': (1, 2, 3)}
    captured = []

    def prepare(body, directories, **options):
        assert body == 7 and options['expected_sha256'] == 'a' * 64
        assert options['nseg_by_edge'] == {3: 3}
        return {'id': body, 'morphology_sha256': options['expected_sha256'],
            'geometry': {'edge_node_ids': np.array([3, 3, 3, 4]),
                         'grid': [(3, 0, 3), (3, 1, 3), (3, 2, 3), (4, 0, 1)]}}

    monkeypatch.setattr(refined_population, 'prepare_registered_cell', prepare)
    transform = refined_population.refined_cell_transform({7: {3: 3}}, [], params,
        duration_ms=10, capture_original=captured.extend)
    assert transform({'id': 8}) == {'id': 8}
    result = transform(original)
    assert captured == [original]
    assert result['geometry']['segment_index'].tolist() == [0, 1, 2, 0]
    assert result['initial_gates'] == original['initial_gates']
    with pytest.raises(ValueError, match='grid'):
        refined_population.refined_cell_transform({7: {3: 2}}, [], params, duration_ms=10)


def test_uniform_refinement_uses_verified_swc_without_neuron(monkeypatch):
    from service.infrastructure.stimulation.experimental_gpu.fast_cable import Params

    swc = '1 2 0 0 0 20 -1\n2 2 1000 0 0 20 1\n3 2 2000 0 0 20 2\n'
    monkeypatch.setattr(refined_population, 'read_skeleton',
                        lambda *_args, **_kwargs: {'swc': swc})
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=100., conductivity_s_m=.3, clearance_um=.1)
    cell = refined_population.uniform_refined_cell(7, [], expected_sha256='a' * 64,
                                                    params=params, nseg=3)
    assert cell['morphology_sha256'] == 'a' * 64
    assert cell['geometry']['grid'] == [(2, 0, 3), (2, 1, 3), (2, 2, 3),
                                         (3, 0, 3), (3, 1, 3), (3, 2, 3)]
    assert cell['geometry']['starts_um'].shape == (6, 3)
    captured = []
    transform = refined_population.uniform_cell_transform({7: 3}, [], params,
                                                           capture_original=captured.extend)
    original = {'id': 7, 'morphology_sha256': 'a' * 64}
    assert transform(original)['geometry']['grid'] == cell['geometry']['grid']
    assert captured == [original]


@pytest.mark.skipif(os.environ.get('AISCS_TEST_CUDA') != '1', reason='Explicit GPU check')
def test_refined_cell_event_and_recording_on_gpu(monkeypatch):
    import nvidia.cuda_nvcc as nvcc
    import nvidia.cuda_runtime as runtime
    from numba.cuda import cuda_paths

    monkeypatch.setenv('CUDA_HOME', next(iter(nvcc.__path__)))
    paths = cuda_paths.get_cuda_paths()
    monkeypatch.setitem(paths, 'cudalib_dir', paths['cudalib_dir']._replace(
        info=str(Path(next(iter(runtime.__path__))) / 'bin')))
    from service.infrastructure.stimulation.experimental_gpu.batch_solver import (
        solve_prepared_batch,
    )
    from service.infrastructure.stimulation.experimental_gpu.fast_cable import Params

    swc = '1 2 0 0 0 20 -1\n2 2 1000 0 0 20 1\n3 2 2000 0 0 20 2\n'
    monkeypatch.setattr(refined_population, 'read_skeleton',
                        lambda *_args, **_kwargs: {'swc': swc})
    params = Params(source_um=(100., 100., 100.), return_um=(200., 100., 100.),
                    current_na=100., conductivity_s_m=.3, clearance_um=.1)
    cell = refined_population.uniform_refined_cell(7, [], expected_sha256='a' * 64,
                                                    params=params, nseg=3)
    event = {'child_node_id': 2, 'position': 5 / 6, 'time_ms': .1,
             'weight_us': .01, 'tau1_ms': .1, 'tau2_ms': 1., 'reversal_mv': 0.}
    table = np.tile([.5, 1., .5, 1., .5, 1.], (201, 1))
    traces = []
    for events in ([], [event]):
        result = []
        solve_prepared_batch([dict(cell, events=events)], [0.] * 21, table,
            output_budget_bytes=1024 * 1024, window_steps=10, cell_major=True,
            recording_coefficients={7: [1.] * 6}, selected_indices={7: [2]},
            device_window_sink=lambda _a, _b, rows, target=result: target.append(rows[0]))
        traces.append(np.concatenate([row['selected_voltage_mv'][0] for row in result]))
        assert np.isfinite(np.concatenate([row['neural_uv'] for row in result])).all()
    assert np.max(np.abs(traces[1] - traces[0])) > 0
