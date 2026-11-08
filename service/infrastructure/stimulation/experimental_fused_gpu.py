"""Experimental fused GPU field summaries; not enabled in the service.

Only independently validated, bounded morphology entries may be passed here.
Results are idealized field descriptors, not excitation or biological activity.
"""
import math

import numpy as np
from numba import cuda, float64, int32

from service.infrastructure.stimulation.network_field import _gpu_batch
from service.infrastructure.stimulation.point_field import bipolar_potential_mv


@cuda.jit(device=True)
def potential(points, index, source, target, factor):
    d1 = 0.
    d2 = 0.
    for axis in range(3):
        d1 += (points[index, axis] - source[axis]) ** 2
        d2 += (points[index, axis] - target[axis]) ** 2
    return factor * (1. / math.sqrt(d1) - 1. / math.sqrt(d2))


@cuda.jit
def clearance_check(points, parents, counts, radii, source, target, clearance, flags):
    i = cuda.grid(1)
    if i >= len(parents):
        return
    flags[i] = 0
    parent = parents[i]
    for which in range(2):
        contact = source if which == 0 else target
        distance_squared = 0.
        coordinate_scale = 1.
        for axis in range(3):
            distance_squared += (points[i, axis] - contact[axis]) ** 2
            coordinate_scale += abs(points[i, axis]) + abs(contact[axis])
        if not math.isfinite(distance_squared):
            flags[i] |= 16
            continue
        uncertainty = 1e-10 * coordinate_scale
        if abs(math.sqrt(distance_squared) - clearance) <= uncertainty:
            flags[i] |= 32
        if distance_squared <= clearance * clearance:
            flags[i] |= 1
        if parent < 0:
            if counts[i] == 0:
                limit = clearance + radii[i]
                if abs(math.sqrt(distance_squared) - limit) <= uncertainty:
                    flags[i] |= 32
                if distance_squared <= limit ** 2:
                    flags[i] |= 8
            continue
        norm, projection = 0., 0.
        for axis in range(3):
            vector = points[i, axis] - points[parent, axis]
            norm += vector * vector
            projection += (contact[axis] - points[parent, axis]) * vector
        radius = radii[i]
        if radii[parent] > radius:
            radius = radii[parent]
        if (not math.isfinite(norm) or not math.isfinite(projection)
                or not math.isfinite(clearance + radius)):
            flags[i] |= 16
            continue
        if norm == 0.:
            # A zero-length segment needs the current implementation's explicit policy.
            flags[i] |= 64
            if abs(math.sqrt(distance_squared) - (clearance + radius)) <= uncertainty:
                flags[i] |= 32
            if distance_squared <= (clearance + radius) ** 2:
                flags[i] |= 2
            continue
        fraction = projection / norm
        if fraction < 0.:
            fraction = 0.
        elif fraction > 1.:
            fraction = 1.
        nearest_squared = 0.
        for axis in range(3):
            nearest = points[parent, axis] + fraction * (points[i, axis] - points[parent, axis])
            nearest_squared += (nearest - contact[axis]) ** 2
        if not math.isfinite(nearest_squared):
            flags[i] |= 16
            continue
        for axis in range(3):
            coordinate_scale += abs(points[parent, axis])
        uncertainty = 1e-10 * coordinate_scale
        if abs(math.sqrt(nearest_squared) - (clearance + radius)) <= uncertainty:
            flags[i] |= 32
        if nearest_squared <= (clearance + radius) ** 2:
            flags[i] |= 4


@cuda.jit
def extrema(points, parents, children, counts, offsets, ids, source, target, factor,
            flags, out_values, out_ids, out_counts, out_second):
    neuron, lane = cuda.blockIdx.x, cuda.threadIdx.x
    values = cuda.shared.array(128, float64)
    seconds = cuda.shared.array(128, float64)
    indexes = cuda.shared.array(128, int32)
    numbers = cuda.shared.array(128, int32)
    unsafe = cuda.shared.array(128, int32)
    numeric_faults = cuda.shared.array(128, int32)
    start, end = offsets[neuron], offsets[neuron + 1]
    has_unsafe = 0
    for i in range(start + lane, end, cuda.blockDim.x):
        if flags[i] != 0:
            has_unsafe = 1
    unsafe[lane] = has_unsafe
    cuda.syncthreads()
    stride = 64
    while stride:
        if lane < stride:
            unsafe[lane] |= unsafe[lane + stride]
        cuda.syncthreads()
        stride //= 2
    if unsafe[0]:
        if lane == 0:
            out_values[neuron], out_ids[neuron] = 0., -1
            out_counts[neuron], out_second[neuron] = -1, -1.
        return
    best, second, best_index, count, numeric_fault = -1., -1., -1, 0, 0
    for i in range(start + lane, end, cuda.blockDim.x):
        parent, child = parents[i], children[i]
        if parent < 0 or counts[i] != 1:
            continue
        before, after = 0., 0.
        for axis in range(3):
            before += (points[i, axis] - points[parent, axis]) ** 2
            after += (points[child, axis] - points[i, axis]) ** 2
        before, after = math.sqrt(before), math.sqrt(after)
        if not math.isfinite(before) or not math.isfinite(after):
            numeric_fault = 1
            continue
        if before == 0. or after == 0.:
            continue
        a = potential(points, parent, source, target, factor)
        b = potential(points, i, source, target, factor)
        c = potential(points, child, source, target, factor)
        v = 2. * ((c - b) / after - (b - a) / before) / (before + after)
        if (not math.isfinite(a) or not math.isfinite(b) or not math.isfinite(c)
                or not math.isfinite(v)):
            numeric_fault = 1
            continue
        count += 1
        if abs(v) > best or (abs(v) == best and i < best_index):
            second = best
            best, best_index = abs(v), i
        elif abs(v) > second:
            second = abs(v)
    values[lane], seconds[lane], indexes[lane], numbers[lane] = best, second, best_index, count
    numeric_faults[lane] = numeric_fault
    cuda.syncthreads()
    stride = 64
    while stride:
        if lane < stride:
            other = values[lane + stride]
            other_index = indexes[lane + stride]
            if other > values[lane] or (other == values[lane] and other_index >= 0
                                         and (indexes[lane] < 0 or other_index < indexes[lane])):
                candidate = values[lane]
                if seconds[lane + stride] > candidate:
                    candidate = seconds[lane + stride]
                seconds[lane] = candidate
                values[lane], indexes[lane] = other, other_index
            else:
                if other > seconds[lane]:
                    seconds[lane] = other
            numbers[lane] += numbers[lane + stride]
            numeric_faults[lane] |= numeric_faults[lane + stride]
        cuda.syncthreads()
        stride //= 2
    if lane == 0:
        if numeric_faults[0]:
            out_values[neuron], out_ids[neuron] = math.nan, -1
            out_counts[neuron], out_second[neuron] = -1, -1.
            return
        index = indexes[0]
        out_counts[neuron] = numbers[0]
        out_second[neuron] = seconds[0]
        if index < 0:
            out_ids[neuron], out_values[neuron] = -1, 0.
        else:
            before, after = 0., 0.
            parent, child = parents[index], children[index]
            for axis in range(3):
                before += (points[index, axis] - points[parent, axis]) ** 2
                after += (points[child, axis] - points[index, axis]) ** 2
            before, after = math.sqrt(before), math.sqrt(after)
            a = potential(points, parent, source, target, factor)
            b = potential(points, index, source, target, factor)
            c = potential(points, child, source, target, factor)
            out_values[neuron] = 2. * ((c - b) / after - (b - a) / before) / (before + after)
            out_ids[neuron] = ids[index]


def pack(entries):
    points, parents, children, counts, vertex_ids, radii, offsets = [], [], [], [], [], [], [0]
    for entry in entries:
        ids, xyz, parent, radius = (np.asarray(value) for value in entry['geometry'])
        n, base = len(ids), offsets[-1]
        if (not n or np.asarray(ids).dtype.kind not in 'iu'
                or np.any(ids <= 0) or np.any(ids >= 2**31)
                or np.asarray(parent).shape != (n,) or np.asarray(parent).dtype.kind != 'i'
                or np.any(parent < -1) or np.any(parent >= n)
                or np.asarray(xyz).shape != (n, 3) or np.asarray(radius).shape != (n,)
                or not np.isfinite(xyz).all() or not np.isfinite(radius).all()
                or np.any(radius < 0)):
            raise ValueError('Invalid experimental field geometry')
        edges = np.flatnonzero(parent >= 0)
        num_children = np.bincount(parent[edges], minlength=n)
        child = np.full(n, -1, np.int32)
        child[parent[edges]] = edges + base
        points.append(xyz)
        parents.append(np.where(parent >= 0, parent + base, -1).astype(np.int32))
        children.append(child)
        counts.append(num_children.astype(np.int32))
        vertex_ids.append(np.asarray(ids, dtype=np.int32))
        radii.append(radius)
        offsets.append(base + n)
    return (np.concatenate(points), np.concatenate(parents), np.concatenate(children),
            np.concatenate(counts), np.asarray(offsets, np.int32), np.concatenate(vertex_ids),
            np.concatenate(radii))


def _run(entries, source_um, return_um, current_na, conductivity_s_m, clearance_um):
    arrays = pack(entries)
    dev = [cuda.to_device(a) for a in arrays]
    source = cuda.to_device(np.asarray(source_um, dtype=np.float64))
    target = cuda.to_device(np.asarray(return_um, dtype=np.float64))
    values = cuda.device_array(len(entries), dtype=np.float64)
    ids = cuda.device_array(len(entries), dtype=np.int32)
    counts = cuda.device_array(len(entries), dtype=np.int32)
    second = cuda.device_array(len(entries), dtype=np.float64)
    flags = cuda.device_array(len(arrays[1]), dtype=np.uint8)
    clearance_check[(len(flags) + 255) // 256, 256](dev[0], dev[1], dev[3], dev[6],
                                                    source, target, clearance_um, flags)
    extrema[len(entries), 128](*dev[:6], source, target,
                              current_na / (4 * math.pi * conductivity_s_m),
                              flags, values, ids, counts, second)
    return (values.copy_to_host(), ids.copy_to_host(), counts.copy_to_host(), flags.copy_to_host(),
            second.copy_to_host())


def experimental_summaries(entries, source_um, return_um, current_na, conductivity_s_m, *,
                           clearance_um, allow_degenerate=False):
    """Return field-only summaries and number of conservative per-cell fallbacks.

    Entries must come from a verified geometry snapshot. This prototype is not
    currently routed through the executor; numerical guards remain under audit.
    """
    bipolar_potential_mv(np.empty((0, 3)), source_um, return_um, current_na, conductivity_s_m,
                         clearance_um=clearance_um)
    if type(allow_degenerate) is not bool or not isinstance(entries, (list, tuple)):
        raise ValueError('Invalid experimental field input')
    if not entries:
        return [], 0
    if len(entries) > 1024 or sum(len(entry['geometry'][0]) for entry in entries) > 1_000_000:
        raise ValueError('Experimental field batch exceeds the bounded GPU geometry limit')
    if not cuda.is_available():
        raise RuntimeError('CUDA field backend is unavailable')
    values, vertices, counts, flags, second = _run(
        entries, source_um, return_um, current_na, conductivity_s_m, clearance_um)
    output, offset, fallbacks = [], 0, 0
    for i, entry in enumerate(entries):
        skeleton, geometry = entry['skeleton'], entry['geometry']
        ids, points, parents, _ = geometry
        size = len(points)
        unsafe = np.bitwise_or.reduce(flags[offset:offset + size], initial=0)
        offset += size
        near_tie = (current_na != 0. and counts[i] > 1 and
                    abs(abs(values[i]) - second[i]) <= 1e-12 + 1e-9 * abs(values[i]))
        if unsafe or near_tie or (counts[i] and not np.isfinite(values[i])):
            fallbacks += 1
            output.extend(_gpu_batch([entry], source_um, return_um, current_na, conductivity_s_m,
                                     clearance_um, allow_degenerate))
            continue
        children = np.flatnonzero(parents >= 0)
        child_counts = np.bincount(parents[children], minlength=size)
        candidates = int(np.count_nonzero((parents >= 0) & (child_counts == 1)))
        output.append({'body_id': skeleton['body_id'], 'status': 'ok',
                       'source_sha256': skeleton['sha256'], 'vertices': len(ids),
                       'curvature_vertices': int(counts[i]),
                       'max_abs_curvature_signed_mv_per_um2': (
                           float(values[i]) if counts[i] else None),
                       'extremum_vertex_id': int(vertices[i]) if counts[i] else None,
                       'coordinate_frame': 'male-cns-v1.0-native-um',
                       'interpretation': 'field-only',
                       'omitted_zero_length_edges': 0,
                       'omitted_curvature_vertices': candidates - int(counts[i])})
    return output, fallbacks
