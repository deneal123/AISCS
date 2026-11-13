import numpy as np
import pytest

from service.application.feedback.cell_cache import CellSolutionCache
from service.infrastructure.stimulation.experimental_gpu.registered_batch import (
    run_registered_batch,
)


def test_recording_configuration_mismatch_rejected_before_preparation(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('Morphology preparation should not start')

    monkeypatch.setattr(
        'service.infrastructure.stimulation.experimental_gpu.registered_batch.prepare_registered_cell',
        unexpected)
    with pytest.raises(ValueError, match='configuration'):
        run_registered_batch([{'id': 1}], [], [0., 1.], source_um=[0, 0, 0],
                             return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
                             clearance_um=1., output_budget_bytes=1000,
                             recording_config={'source_um': [9, 0, 0]})


def test_duplicate_ids_rejected_before_preparation():
    with pytest.raises(ValueError, match='batch'):
        run_registered_batch([{'id': 1}, {'id': 1}], [], [0., 1.], source_um=[0, 0, 0],
                             return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
                             clearance_um=1., output_budget_bytes=1000)


def test_unsupported_fixed_timestep_rejected_before_preparation(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('Morphology preparation should not start')

    monkeypatch.setattr(
        'service.infrastructure.stimulation.experimental_gpu.registered_batch.prepare_registered_cell',
        unexpected)
    config = {'source_um': [0, 0, 0], 'return_um': [1, 0, 0], 'current_na': 1.,
              'conductivity_s_m': .3, 'clearance_um': 1., 'duration_ms': .025, 'dt_ms': .1}
    with pytest.raises(ValueError, match='Unsupported'):
        run_registered_batch([{'id': 1}], [], [0., 1.], source_um=[0, 0, 0],
                             return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
                             clearance_um=1., output_budget_bytes=1000,
                             recording_config=config)


def test_split_batches_restore_order_and_progress(monkeypatch):
    module = 'service.infrastructure.stimulation.experimental_gpu.registered_batch.'
    sizes = {1: 10, 2: 1, 3: 2}

    def prepare(body, *_args, **_kwargs):
        return {'id': body, 'geometry': {'grid': [None] * sizes[body]},
                'morphology_sha256': str(body) * 64, 'morphology_source': 'fixture'}

    def solve(cells, _stimulus, _table, *, progress, **_kwargs):
        progress(1, 1)
        return {'cells': [{'id': cell['id']} for cell in cells],
                'time_ms': np.array([0., .025]), 'table_clamped_cell_ids': []}

    monkeypatch.setattr(module + 'prepare_registered_cell', prepare)
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: (None, [0., 0., 0.]))
    monkeypatch.setattr(module + 'solve_prepared_batch', solve)
    monkeypatch.setattr(module + 'as_reference_arrays', lambda _g, output, _t: output)
    progress = []
    result = run_registered_batch([{'id': body, 'expected_sha256': 'a' * 64}
                                   for body in sizes], [], [0., 1.],
        source_um=[0, 0, 0], return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
        clearance_um=1., output_budget_bytes=500,
        progress=lambda done, total: progress.append((done, total)))
    assert [item['id'] for item in result] == [1, 2, 3]
    assert progress == [(1, 2), (2, 2)]


def test_geometry_cache_rechecks_morphology_and_events(monkeypatch):
    module = 'service.infrastructure.stimulation.experimental_gpu.registered_batch.'
    calls = []

    def prepare(body, *_args, **kwargs):
        calls.append('prepare')
        return {'id': body, 'geometry': {'grid': [(2, 0, 1)]}, 'events': kwargs['events'],
                'morphology_sha256': 'a' * 64, 'morphology_source': 'fixture'}

    def verify(body, _dirs, *, expected_sha256):
        calls.append(('verify', body, expected_sha256))
        return {'source': 'fixture'}

    monkeypatch.setattr(module + 'prepare_registered_cell', prepare)
    monkeypatch.setattr('service.infrastructure.connectome.morphology_repository.read_skeleton',
                        verify)
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: (None, [0., 0., 0.]))
    monkeypatch.setattr(module + 'solve_prepared_batch', lambda cells, *_a, **_k: {
        'cells': [{'id': cell['id']} for cell in cells], 'time_ms': np.array([0., .025]),
        'table_clamped_cell_ids': []})
    monkeypatch.setattr(module + 'as_reference_arrays', lambda _g, output, _t: output)
    cache = CellSolutionCache(100000, policy='stable')
    request = [{'id': 1, 'expected_sha256': 'a' * 64, 'events': []}]
    kwargs = {'source_um': [0, 0, 0], 'return_um': [1, 0, 0], 'current_na': 1.,
              'conductivity_s_m': .3, 'clearance_um': 1., 'output_budget_bytes': 10000,
              'geometry_cache': cache}
    run_registered_batch(request, [], [0., 1.], **kwargs)
    run_registered_batch(request, [], [0., 1.], **kwargs)
    assert calls == ['prepare', ('verify', 1, 'a' * 64)]
    request[0]['events'] = [{'child_node_id': 999}]
    with pytest.raises(ValueError):
        run_registered_batch(request, [], [0., 1.], **kwargs)
    request[0]['events'] = []
    request[0]['nseg_by_edge'] = []
    with pytest.raises(ValueError, match='morphology request'):
        run_registered_batch(request, [], [0., 1.], **kwargs)


def test_oversized_cell_reports_required_budget_before_gpu_launch(monkeypatch):
    module = 'service.infrastructure.stimulation.experimental_gpu.registered_batch.'
    monkeypatch.setattr(module + 'prepare_registered_cell', lambda *_a, **_k: {
        'id': 123, 'geometry': {'grid': [None] * 100}})
    monkeypatch.setattr(module + 'prepare_hh_table', lambda: (None, [0., 0., 0.]))
    with pytest.raises(ValueError, match=r'cell 123: requires 3232 bytes, limit 1000 bytes'):
        run_registered_batch([{'id': 123, 'expected_sha256': 'a' * 64}], [], [0., 1.],
            source_um=[0, 0, 0], return_um=[1, 0, 0], current_na=1., conductivity_s_m=.3,
            clearance_um=1., output_budget_bytes=1000)
