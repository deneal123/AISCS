"""Linux integration check for terminating the solver and its child worker."""
import multiprocessing as mp
import os
import signal
import sys
import time
from uuid import uuid4

import pytest

from service.infrastructure.execution.process import Executions


def _wait_forever():
    while True:
        time.sleep(1)


def _solver_with_worker(ready):
    os.setsid()
    worker = mp.get_context('spawn').Process(target=_wait_forever)
    worker.start()
    ready.put(worker.pid)
    _wait_forever()


def _pool_worker(path):
    with open(path, 'w', encoding='ascii') as stream:
        stream.write(str(os.getpid()))
    _wait_forever()


def _solver_with_preparation_pool(ready, worker_path):
    from service.infrastructure.stimulation.experimental_gpu.prepare_batches import (
        create_preparation_pool,
    )

    os.setsid()
    with create_preparation_pool(2) as pool:
        pool.submit(_pool_worker, worker_path)
        deadline = time.monotonic() + 20
        while not os.path.exists(worker_path) and time.monotonic() < deadline:
            time.sleep(.05)
        with open(worker_path, encoding='ascii') as stream:
            ready.put(int(stream.read()))
        _wait_forever()


def _alive_non_zombie(pid):
    try:
        with open(f'/proc/{pid}/stat', encoding='ascii') as stream:
            state = stream.read().rsplit(')', 1)[1].split()[0]
        return state != 'Z'
    except FileNotFoundError:
        return False


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process groups required')
@pytest.mark.parametrize('real_pool', [False, True])
def test_cancel_stops_owned_solver_and_worker(tmp_path, real_pool):
    context = mp.get_context('spawn')
    ready = context.Queue()
    target = _solver_with_preparation_pool if real_pool else _solver_with_worker
    args = (ready, str(tmp_path / 'pool-worker.pid')) if real_pool else (ready,)
    child = context.Process(target=target, args=args)
    child.start()
    worker_pid = None
    try:
        worker_pid = ready.get(timeout=20)
        assert os.getpgid(child.pid) == child.pid == os.getpgid(worker_pid)
        manager = Executions(tmp_path)
        execution_id = str(uuid4())
        manager.save({'execution_id': execution_id, 'kind': 'experimental-coupled-population',
                      'status': 'running', 'configuration_sha256': 'a' * 64,
                      'source_sha256': 'b' * 64, 'acknowledged': False})
        manager.processes[execution_id] = child
        assert manager.cancel(execution_id)['status'] == 'cancelled'
        deadline = time.monotonic() + 5
        while _alive_non_zombie(worker_pid) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not child.is_alive() and not _alive_non_zombie(worker_pid)
    finally:
        if child.is_alive():
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.join(timeout=5)
        if worker_pid and _alive_non_zombie(worker_pid):
            os.kill(worker_pid, signal.SIGKILL)
        ready.close()
