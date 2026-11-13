"""Bounded process-parallel preparation of registered experimental cells."""

import multiprocessing as mp
import os
import sys
from concurrent.futures import ProcessPoolExecutor

from service.infrastructure.execution.ordered_pool import ordered_process_map
from service.infrastructure.execution.pool_lifecycle import guard_pool_owner

from .prepare import prepare_registered_cell


def _prepare_one(task):
    body_id, directories, kwargs = task
    return prepare_registered_cell(body_id, directories, **kwargs)


def prepare_registered_batch(requests, directories, *, workers=1, executor=None):
    """Prepare cells in input order in isolated processes, without GPU work.

    Requests are internal, already-verified input dictionaries. Worker count
    bounds in-flight tasks, not total RAM or the returned geometries; callers
    must also bound batch size and process memory. This is not a service API.
    """
    if (not isinstance(requests, list) or not requests or type(workers) is not int
            or not 1 <= workers <= 8 or not isinstance(directories, list)
            or any(not isinstance(row, dict) or set(row) != {'body_id', 'parameters'}
                   or type(row['body_id']) is not int or row['body_id'] <= 0
                   or not isinstance(row['parameters'], dict) for row in requests)
            or len({row['body_id'] for row in requests}) != len(requests)):
        raise ValueError('Invalid bounded cell preparation batch')
    tasks = ((row['body_id'], directories, row['parameters']) for row in requests)
    cells = list(ordered_process_map(_prepare_one, tasks, workers=workers, executor=executor))
    if [cell.get('id') for cell in cells] != [row['body_id'] for row in requests]:
        raise ValueError('Prepared cell identity or ordering mismatch')
    return cells


def create_preparation_pool(workers):
    """Create an owner-guarded pool; caller must close it via a context manager."""
    if (type(workers) is not int or not 2 <= workers <= 8 or sys.platform != 'linux'
            or mp.current_process().daemon):
        raise ValueError('Preparation pool requires a non-daemon Linux owner and 2–8 workers')
    return ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context('spawn'),
                               initializer=guard_pool_owner, initargs=(os.getpid(),))
