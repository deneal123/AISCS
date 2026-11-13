"""Bounded ordered process mapping for independent detailed-cell calculations."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from service.infrastructure.execution.pool_lifecycle import guard_pool_owner


@dataclass(frozen=True)
class LocalResult:
    """An already verified result that must remain in the owning process."""

    value: Any


def ordered_process_map(function, tasks, *, workers: int, executor=None):
    """Yield results in input order with at most one submitted task per worker.

    The owner must cancel its process group on external interruption. Closing
    this iterator cancels tasks that have not started and waits for running
    tasks; it does not forcibly stop them. Linux parent-death signalling is
    installed in every worker. No user-provided code is accepted by the API;
    this is an internal helper for registered solver functions.
    """
    if (not callable(function) or type(workers) is not int or not 1 <= workers <= 8
            or (executor is not None and
                (workers == 1 or not isinstance(executor, ProcessPoolExecutor)))):
        raise ValueError('Invalid ordered process mapping')
    if workers > 1 and (sys.platform != 'linux' or mp.current_process().daemon):
        raise ValueError('Parallel mapping requires a non-daemon Linux owner')

    iterator = iter(tasks)
    pending = deque()
    try:
        if workers == 1:
            for task in iterator:
                yield task.value if isinstance(task, LocalResult) else function(task)
            return
        manager = (nullcontext(executor) if executor is not None else
                   ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                                       initializer=guard_pool_owner, initargs=(os.getpid(),)))
        with manager as pool:
            def submit(task):
                if isinstance(task, LocalResult):
                    future = Future()
                    future.set_result(task.value)
                    return future
                return pool.submit(function, task)

            try:
                for _ in range(workers):
                    try:
                        pending.append(submit(next(iterator)))
                    except StopIteration:
                        break
                while pending:
                    result = pending.popleft().result()
                    yield result
                    try:
                        pending.append(submit(next(iterator)))
                    except StopIteration:
                        pass
            finally:
                for future in pending:
                    future.cancel()
    finally:
        close = getattr(iterator, 'close', None)
        if callable(close):
            close()
