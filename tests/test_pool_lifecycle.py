import multiprocessing as mp
import os
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from service.infrastructure.execution.pool_lifecycle import guard_pool_owner


def _wait_forever(pid_path):
    target = Path(pid_path)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(str(os.getpid()), encoding='ascii')
    temporary.replace(target)
    while True:
        time.sleep(.05)


def _owned_group(pid_path):
    os.setsid()
    with ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context('spawn'),
                             initializer=guard_pool_owner, initargs=(os.getpid(),)) as pool:
        pool.submit(_wait_forever, pid_path).result()


def _alive(pid):
    try:
        status = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
        return status not in ('Z', 'X')
    except FileNotFoundError:
        return False


def _reject_wrong_parent(expected_pid):
    try:
        guard_pool_owner(expected_pid)
    except RuntimeError:
        return
    raise AssertionError('Worker accepted a different owner')


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux parent-death signalling')
def test_worker_refuses_work_if_owner_was_already_replaced():
    child = mp.get_context('spawn').Process(target=_reject_wrong_parent,
                                            args=(os.getpid() + 1,))
    child.start()
    try:
        child.join(10)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
            child.join(5)


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux parent-death signalling')
def test_pool_worker_stops_after_its_owning_process_is_killed(tmp_path):
    pid_path = tmp_path / 'worker.pid'
    leader = mp.get_context('spawn').Process(target=_owned_group, args=(str(pid_path),))
    leader.start()
    worker_pid = None
    try:
        deadline = time.monotonic() + 20
        while not pid_path.is_file() and time.monotonic() < deadline:
            if not leader.is_alive():
                pytest.fail('Pool owner exited before its worker started')
            time.sleep(.05)
        assert pid_path.is_file()
        worker_pid = int(pid_path.read_text(encoding='ascii'))
        assert os.getpgid(leader.pid) == leader.pid
        assert os.getpgid(worker_pid) == leader.pid
        leader.kill()
        leader.join(5)
        assert not leader.is_alive()
        deadline = time.monotonic() + 5
        while _alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(.05)
        assert not _alive(worker_pid)
    finally:
        # Only the child group whose membership was verified above is eligible.
        if worker_pid is not None and _alive(worker_pid):
            try:
                if os.getpgid(worker_pid) == leader.pid:
                    os.killpg(leader.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if leader.is_alive():
            leader.kill()
        leader.join(5)


@pytest.mark.parametrize('bad', [0, -1, True, 1.5, '1'])
def test_pool_owner_identity_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError, match='owner PID'):
        guard_pool_owner(bad)
