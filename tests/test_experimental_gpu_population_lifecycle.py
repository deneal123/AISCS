import threading
from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu import batch_solver, population_replay


def _run(**kwargs):
    return population_replay.solve_population(
        None, None, None, audited_sources=None, params=None,
        segment_budget=10, output_budget_bytes=10, reduce_trees=False,
        prefetch=1, **kwargs,
    )


def test_closed_consumer_releases_blocked_preparation(monkeypatch):
    finished = threading.Event()
    produced = threading.Event()

    def batches(*args, **kwargs):
        try:
            for i in range(10000):
                if i == 3:
                    produced.set()
                yield [{'id': i, 'geometry': None}]
        finally:
            finished.set()

    monkeypatch.setattr(population_replay, 'iter_cell_batches', batches)
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *_: None)
    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', lambda *a, **kw: {})
    replay = _run()
    assert next(replay)[0] == [0]
    # Allow both bounded queues to fill while the consumer is paused.
    assert produced.wait(2)
    replay.close()
    assert finished.wait(2)


def test_cancel_during_preparation_releases_producer(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def batches(*args, **kwargs):
        try:
            started.set()
            release.wait(2)
            yield [{'id': 1, 'geometry': None}]
        finally:
            finished.set()

    monkeypatch.setattr(population_replay, 'iter_cell_batches', batches)
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *_: None)

    def cancelled():
        if started.is_set():
            raise RuntimeError('cancelled')

    replay = _run(check_cancelled=cancelled)
    try:
        with pytest.raises(RuntimeError, match='cancelled'):
            next(replay)
    finally:
        release.set()
    assert finished.wait(2)


def test_preparation_errors_reach_consumer(monkeypatch):
    def batches(*args, **kwargs):
        raise ValueError('invalid morphology')
        yield

    monkeypatch.setattr(population_replay, 'iter_cell_batches', batches)
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *_: None)
    with pytest.raises(ValueError, match='invalid morphology'):
        next(_run())


def test_recording_batches_are_split_before_gpu_budget_is_exceeded(monkeypatch):
    cells = [{'id': body, 'geometry': {'parents': [0, 1], 'segment_nodes': [1]}}
             for body in (1, 2)]
    monkeypatch.setattr(population_replay, 'iter_cell_batches', lambda *a, **k: iter([cells]))
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *a: ('packed',))
    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', lambda *a, **k: {})

    def factory(group):
        return {'recording_coefficients': {cell['id']: [1.] for cell in group},
                'selected_indices': {cell['id']: [] for cell in group}, 'sink': lambda *a: None}

    output = list(population_replay.solve_population(
        None, [0., 0., 0.], None, audited_sources=None, params=None,
        segment_budget=10, output_budget_bytes=200, reduce_trees=False,
        device_window_factory=factory, recording_max_selected=0))
    assert [ids for ids, _ in output] == [[1], [2]]


def test_recording_selection_ceiling_can_exceed_small_cell_size(monkeypatch):
    cells = [{'id': 1, 'geometry': {'parents': [0, 1], 'segment_nodes': [1]}},
             {'id': 2, 'geometry': {'parents': [0, 1, 2, 3, 4],
                                    'segment_nodes': [1, 2, 3, 4]}}]
    monkeypatch.setattr(population_replay, 'iter_cell_batches', lambda *a, **k: iter([cells]))
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *a: ('packed',))
    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', lambda *a, **k: {})

    def factory(group):
        return {'recording_coefficients': {cell['id']: [1.] for cell in group},
                'selected_indices': {cell['id']: list(range(len(cell['geometry']['segment_nodes'])))
                                     for cell in group}, 'sink': lambda *a: None}

    output = list(population_replay.solve_population(
        None, [0., 0., 0.], None, audited_sources=None, params=None,
        segment_budget=10, output_budget_bytes=10000, reduce_trees=False,
        device_window_factory=factory, recording_max_selected=4))
    assert sorted(body for ids, _ in output for body in ids) == [1, 2]


def test_packing_error_stops_preparation(monkeypatch):
    finished = threading.Event()

    def batches(*args, **kwargs):
        try:
            for i in range(10000):
                yield [{'id': i, 'geometry': None}]
        finally:
            finished.set()

    def fail(*args):
        raise ValueError('packing failed')

    monkeypatch.setattr(population_replay, 'iter_cell_batches', batches)
    monkeypatch.setattr(batch_solver, 'build_cell_major', fail)
    with pytest.raises(ValueError, match='packing failed'):
        next(_run())
    assert finished.wait(2)


def test_closed_windowed_consumer_releases_preparation(monkeypatch):
    finished = threading.Event()
    produced = threading.Event()

    def batches(*args, **kwargs):
        try:
            for i in range(10000):
                if i == 2:
                    produced.set()
                yield [{'id': i, 'geometry': None}]
        finally:
            finished.set()

    monkeypatch.setattr(population_replay, 'iter_cell_batches', batches)
    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', lambda *a, **kw: {})
    replay = _run(window_sink=lambda *a: None)
    assert next(replay)[0] == [0]
    assert produced.wait(2)
    replay.close()
    assert finished.wait(2)


def test_population_device_recording_uses_cell_major_and_checks_identity(monkeypatch):
    cells = [{'id': 7, 'geometry': {'marker': True}}]
    monkeypatch.setattr(population_replay, 'iter_cell_batches', lambda *a, **k: iter([cells]))
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *a: ('packed',))
    received = []

    def solver(group, stimulus, table, **options):
        assert options['cell_major'] is True
        assert options['record_traces'] is True
        assert options['cell_major_packed'] == ('packed',)
        assert options['recording_coefficients'] == {7: [1.]}
        assert options['cell_major_block_threads'] == 128
        options['device_window_sink'](0, 1, [{'id': 7, 'neural_uv': [2.]}])
        return {'ok': True}

    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', solver)
    def factory(group):
        assert group == cells
        return {'recording_coefficients': {7: [1.]}, 'selected_indices': {7: [0]},
                'sink': lambda start, end, rows: received.append((start, end, rows))}

    assert list(_run(device_window_factory=factory, cell_major_block_threads=128)) == [
        ([7], {'ok': True})]
    assert received == [(0, 1, [{'id': 7, 'neural_uv': [2.]}])]


def test_population_device_recording_rejects_incompatible_sinks():
    with pytest.raises(ValueError, match='recording configuration'):
        next(_run(device_window_factory=lambda _: {}, window_sink=lambda *a: None))


def test_recording_narrowing_keeps_detached_geometry_for_electrodes():
    backing = np.arange(60., dtype=float).reshape(20, 3)
    geometry = {'parents': np.array([-1, 0]), 'conductances': np.array([0., 1.]),
                'segment_nodes': np.array([1]), 'area': np.array([1.]), 'grid': None,
                'starts_um': backing[:1], 'ends_um': backing[1:2],
                'midpoints_um': backing[2:3], 'endpoint_radii_um': backing[3:4, :2],
                'edge_node_ids': np.array([42]), 'segment_index': np.array([0]),
                'unused': backing}
    cell = {'id': 1, 'geometry': geometry, 'field_current_na': np.array([.1]), 'events': [],
            'initial_voltage_mv': -65., 'initial_gates': [.1, .2, .3],
            'morphology_sha256': 'a' * 64}
    narrowed = population_replay._narrow(cell, lambda item, verify: (item, {}), None,
                                         slim=True, recording=True)
    assert 'unused' not in narrowed['geometry']
    assert narrowed['morphology_sha256'] == cell['morphology_sha256']
    for key in ('starts_um', 'ends_um', 'midpoints_um', 'endpoint_radii_um'):
        np.testing.assert_array_equal(narrowed['geometry'][key], geometry[key])
        assert not np.shares_memory(narrowed['geometry'][key], backing)


def test_population_events_build_grid_and_preserve_identity(monkeypatch):
    cells = [{'id': 7, 'geometry': {'edge_node_ids': np.array([42, 42, 42]),
              'segment_index': np.array([0, 1, 2]), 'grid': None}}]
    monkeypatch.setattr(population_replay, 'iter_cell_batches', lambda *a, **k: iter([cells]))
    monkeypatch.setattr(batch_solver, 'build_cell_major', lambda *a: ('packed',))
    def solve(group, stimulus, table, **options):
        assert group[0]['events'] == [{'child_node_id': 42}]
        assert group[0]['geometry']['grid'] == [(42, 0, 3), (42, 1, 3), (42, 2, 3)]
        return {}
    monkeypatch.setattr(batch_solver, 'solve_prepared_batch', solve)
    result = population_replay.solve_population(None, None, None, audited_sources=None,
        params=SimpleNamespace(nseg=3), segment_budget=10, output_budget_bytes=10,
        reduce_trees=False, event_factory=lambda ids: {7: [{'child_node_id': 42}]})
    assert list(result) == [([7], {})]


def test_population_rejects_incomplete_event_schedule(monkeypatch):
    monkeypatch.setattr(population_replay, 'iter_cell_batches',
                        lambda *a, **k: iter([[{'id': 7, 'geometry': {}}]]))
    with pytest.raises(ValueError, match='event schedule'):
        list(_run(event_factory=lambda ids: {}))


def test_event_grid_preserves_nonuniform_discretization():
    import numpy as np
    import pytest

    from service.infrastructure.stimulation.experimental_gpu.population_replay import _event_grid

    geometry = {'edge_node_ids': np.array([7, 7, 7, 9]),
                'grid': [(7, 0, 3), (7, 1, 3), (7, 2, 3), (9, 0, 1)]}
    assert _event_grid(geometry, 1) == geometry['grid']
    geometry['grid'][0] = (8, 0, 3)
    with pytest.raises(ValueError, match='event grid'):
        _event_grid(geometry, 1)
