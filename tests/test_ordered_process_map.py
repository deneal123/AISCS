import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from types import SimpleNamespace

import pytest

from service.infrastructure.execution.ordered_pool import LocalResult, ordered_process_map


def _task(data):
    number, directory, delay = data
    Path(directory, f'started-{number}').write_text(str(os.getpid()), encoding='ascii')
    time.sleep(delay)
    if number == -1:
        raise ValueError('deliberate worker error')
    if number == -2:
        os._exit(7)
    return number, os.getpid()


@pytest.mark.skipif(sys.platform != 'linux', reason='parallel pool requires Linux')
def test_bounded_results_remain_ordered_and_workers_are_reaped(tmp_path):
    tasks = [(0, str(tmp_path), .3), (1, str(tmp_path), 0), (2, str(tmp_path), 0)]
    output = ordered_process_map(_task, tasks, workers=2)
    first = next(output)
    assert first[0] == 0
    assert (tmp_path / 'started-0').is_file() and (tmp_path / 'started-1').is_file()
    assert not (tmp_path / 'started-2').exists()
    rest = list(output)
    assert [item[0] for item in rest] == [1, 2]
    worker_ids = {first[1], *(item[1] for item in rest)}
    assert not worker_ids.intersection(child.pid for child in mp.active_children())


@pytest.mark.skipif(sys.platform != 'linux', reason='parallel pool requires Linux')
@pytest.mark.parametrize('number,error', [(-1, ValueError), (-2, BrokenProcessPool)])
def test_worker_failure_never_returns_a_partial_success(tmp_path, number, error):
    tasks = [(number, str(tmp_path), 0), (1, str(tmp_path), .05)]
    with pytest.raises(error):
        list(ordered_process_map(_task, tasks, workers=2))


@pytest.mark.skipif(sys.platform != 'linux', reason='parallel pool requires Linux')
def test_local_results_keep_order_and_are_not_sent_to_workers(tmp_path):
    local = object()
    tasks = [(0, str(tmp_path), .05), LocalResult(local), (1, str(tmp_path), 0)]
    results = list(ordered_process_map(_task, tasks, workers=2))
    assert [results[0][0], results[2][0]] == [0, 1]
    assert results[1] is local


@pytest.mark.skipif(sys.platform != 'linux', reason='parallel pool requires Linux')
def test_external_pool_is_reused_and_closed_by_its_owner(tmp_path):
    from service.infrastructure.execution.pool_lifecycle import guard_pool_owner

    with ProcessPoolExecutor(max_workers=2, mp_context=mp.get_context('spawn'),
                             initializer=guard_pool_owner, initargs=(os.getpid(),)) as pool:
        first = list(ordered_process_map(_task, [(1, str(tmp_path), 0)], workers=2, executor=pool))
        second = list(ordered_process_map(_task, [(2, str(tmp_path), 0)], workers=2, executor=pool))
        assert first[0][0] == 1 and second[0][0] == 2
    assert not {first[0][1], second[0][1]}.intersection(
        child.pid for child in mp.active_children())


@pytest.mark.parametrize('workers', [1, 2])
def test_closing_mapping_closes_its_task_iterator(tmp_path, workers):
    if workers == 2 and sys.platform != 'linux':
        pytest.skip('parallel pool requires Linux')
    closed = []

    def tasks():
        try:
            yield (0, str(tmp_path), 0)
            yield (1, str(tmp_path), .05)
        finally:
            closed.append(True)

    output = ordered_process_map(_task, tasks(), workers=workers)
    assert next(output)[0] == 0
    output.close()
    assert closed == [True]


@pytest.mark.parametrize('workers', [0, 9, True, 1.5])
def test_invalid_worker_counts_fail_before_consuming_tasks(workers):
    with pytest.raises(ValueError, match='mapping'):
        list(ordered_process_map(_task, [], workers=workers))


def test_parallel_mapping_refuses_a_daemon_owner(monkeypatch):
    monkeypatch.setattr('service.infrastructure.execution.ordered_pool.sys.platform', 'linux')
    monkeypatch.setattr('service.infrastructure.execution.ordered_pool.mp.current_process',
                        lambda: SimpleNamespace(daemon=True))
    with pytest.raises(ValueError, match='non-daemon'):
        list(ordered_process_map(_task, [], workers=2))
