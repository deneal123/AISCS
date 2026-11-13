import threading

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
