"""Optional GPU implementation of the ideal point-electrode field.

Requires a separately provisioned CUDA/Numba environment. This does not run
NEURON on GPU, predict excitation, or model tissue boundaries.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from service.infrastructure.stimulation.point_field import _points, bipolar_potential_mv


@lru_cache(maxsize=1)
def _kernel():
    try:
        from numba import cuda
    except ImportError as exc:
        raise RuntimeError("CUDA field backend is unavailable") from exc
    if not cuda.is_available():
        raise RuntimeError("CUDA field backend is unavailable")

    @cuda.jit
    def evaluate(points, source, target, current, conductivity, clearance, values, invalid):
        index = cuda.grid(1)
        if index >= points.shape[0]:
            return
        first_squared, second_squared = 0., 0.
        for axis in range(3):
            first_squared += (points[index, axis] - source[axis]) ** 2
            second_squared += (points[index, axis] - target[axis]) ** 2
        first, second = math.sqrt(first_squared), math.sqrt(second_squared)
        if not math.isfinite(first) or not math.isfinite(second):
            invalid[index] = 2
        elif first <= clearance or second <= clearance:
            invalid[index] = 1
        else:
            value = current / (4 * math.pi * conductivity) * (1 / first - 1 / second)
            if math.isfinite(value):
                values[index] = value
            else:
                invalid[index] = 2

    return cuda, evaluate


def _potential_and_status(points_um, source_um, return_um, current_na, conductivity_s_m,
                          *, clearance_um):
    """Evaluate one batch and retain per-point status for group isolation."""
    points = np.ascontiguousarray(_points(points_um, "points_um"))
    bipolar_potential_mv(np.empty((0, 3)), source_um, return_um, current_na, conductivity_s_m,
                         clearance_um=clearance_um)
    cuda, evaluate = _kernel()
    if len(points) == 0:
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int8)
    source = np.asarray(source_um, dtype=np.float64)
    target = np.asarray(return_um, dtype=np.float64)
    values = cuda.device_array(len(points), dtype=np.float64)
    invalid = cuda.to_device(np.zeros(len(points), dtype=np.int8))
    evaluate[(len(points) + 255) // 256, 256](
        cuda.to_device(points), cuda.to_device(source), cuda.to_device(target),
        float(current_na), float(conductivity_s_m), float(clearance_um), values, invalid,
    )
    return values.copy_to_host(), invalid.copy_to_host()


def _checked_group(result, statuses):
    if np.any(statuses == 1):
        raise ValueError("Observation point intersects a contact exclusion sphere")
    if np.any(statuses != 0):
        raise ValueError("Contact distance or potential overflow")
    if not np.isfinite(result).all():
        raise ValueError("Potential overflow")
    return result


def bipolar_potential_mv_gpu(points_um, source_um, return_um, current_na, conductivity_s_m,
                             *, clearance_um):
    """Return checked mV values; failures never fall back silently to CPU."""
    values, statuses = _potential_and_status(points_um, source_um, return_um, current_na,
                                              conductivity_s_m, clearance_um=clearance_um)
    return _checked_group(values, statuses)


def bipolar_potential_groups_gpu(groups, source_um, return_um, current_na, conductivity_s_m,
                                 *, clearance_um, max_points=1_000_000, isolate_invalid=False):
    """Evaluate bounded groups together and return one ordered array per neuron.

    A failed group rejects the batch by default. With isolate_invalid=True,
    a ValueError replaces each invalid group without discarding valid peers.
    """
    if type(max_points) is not int or max_points < 1 or type(isolate_invalid) is not bool:
        raise ValueError('max_points must be a positive integer')
    arrays = (np.ascontiguousarray(_points(group, 'points_um')) for group in groups)
    result, pending, count = [], [], 0

    def flush():
        if not pending:
            return
        lengths = [len(group) for group in pending]
        combined = np.concatenate(pending)
        offsets = np.cumsum([0, *lengths])
        if not isolate_invalid:
            values = bipolar_potential_mv_gpu(combined, source_um, return_um,
                                               current_na, conductivity_s_m,
                                               clearance_um=clearance_um)
            result.extend(values[offsets[i]:offsets[i + 1]] for i in range(len(lengths)))
            return
        values, statuses = _potential_and_status(combined, source_um, return_um,
                                                  current_na, conductivity_s_m,
                                                  clearance_um=clearance_um)
        for i in range(len(lengths)):
            start, end = offsets[i:i + 2]
            try:
                result.append(_checked_group(values[start:end], statuses[start:end]))
            except ValueError as exc:
                result.append(exc)

    for points in arrays:
        if len(points) > max_points:
            raise ValueError('Neuron exceeds GPU batch point limit')
        if pending and count + len(points) > max_points:
            flush()
            pending, count = [], 0
        pending.append(points)
        count += len(points)
    flush()
    return result
