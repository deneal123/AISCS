"""Exact conservative cable clearances for previously authenticated SWC bytes."""

from __future__ import annotations

import math

import numpy as np


def _positions_and_order(points, probe_indices, probe_clearance_um):
    positions = np.asarray(points, dtype=float)
    if (positions.ndim != 2 or positions.shape[1:] != (3,)
            or not 1 <= len(positions) <= 64 or not np.isfinite(positions).all()):
        raise ValueError('Invalid contact positions')
    if probe_indices is not None:
        if (not probe_indices or len(set(probe_indices)) != len(probe_indices)
                or any(type(i) is not int or i < 0 or i >= len(positions) for i in probe_indices)
                or not isinstance(probe_clearance_um, int | float)
                or isinstance(probe_clearance_um, bool) or not math.isfinite(probe_clearance_um)):
            raise ValueError('Invalid screening probe')
    order = (list(probe_indices) + [i for i in range(len(positions)) if i not in probe_indices]
             if probe_indices is not None else range(len(positions)))
    return positions, order


def contact_clearances(swc, points, *, probe_indices=None, probe_clearance_um=None):
    """Return all distances for a flagged cell, or None when every probe is clear.

    Results use the maximum endpoint radius, including isolated roots and zero-length
    segments. This only describes the supplied reconstruction, not tissue anatomy.
    """
    positions, order = _positions_and_order(points, probe_indices, probe_clearance_um)

    ids, coordinates, radii, parent_ids = [], [], [], []
    seen = set()
    for line in swc.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#'):
            continue
        if len(fields) != 7:
            raise ValueError('Malformed SWC')
        node, parent = int(fields[0]), int(fields[6])
        point = [float(value) * .008 for value in fields[2:5]]
        radius = float(fields[5]) * .008
        if (node <= 0 or node >= 2**63 or node in seen
                or any(not math.isfinite(value) for value in point)
                or not math.isfinite(radius) or radius < 0):
            raise ValueError('Invalid SWC vertex')
        seen.add(node)
        ids.append(node)
        parent_ids.append(parent)
        coordinates.append(point)
        radii.append(radius)
    if not ids:
        raise ValueError('Empty SWC')
    index = {node: ordinal for ordinal, node in enumerate(ids)}
    try:
        parents = np.asarray([index[parent] if parent != -1 else -1 for parent in parent_ids])
    except KeyError as exc:
        raise ValueError('Missing SWC parent') from exc
    return _geometry_clearances(np.asarray(coordinates), parents, np.asarray(radii), positions,
                                order, probe_indices, probe_clearance_um)


def packed_contact_clearances(geometry, points, *, probe_indices=None, probe_clearance_um=None,
                              _conservative_prefilter=False):
    """Screen geometry read from an independently authenticated packed snapshot."""
    if type(_conservative_prefilter) is not bool:
        raise ValueError('Invalid conservative prefilter setting')
    positions, order = _positions_and_order(points, probe_indices, probe_clearance_um)
    try:
        ids, coordinates, parents, radii = (np.asarray(value) for value in geometry)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid packed geometry') from exc
    count = len(ids) if ids.ndim == 1 else 0
    if (count == 0 or ids.dtype.kind not in 'iu' or np.any(ids <= 0)
            or coordinates.shape != (count, 3) or parents.shape != (count,)
            or radii.shape != (count,) or parents.dtype.kind != 'i'
            or coordinates.dtype != np.float64 or radii.dtype != np.float64
            or np.any(parents < -1) or np.any(parents >= count)
            or not np.isfinite(coordinates).all() or not np.isfinite(radii).all()
            or np.any(radii < 0)):
        raise ValueError('Invalid packed geometry')
    if _conservative_prefilter and probe_indices is not None:
        try:
            from service.infrastructure.stimulation.contacts.broad_phase import may_intersect_box
        except ModuleNotFoundError as exc:
            if exc.name != 'numba':
                raise
        else:
            if not may_intersect_box(coordinates, parents, radii, positions,
                                     np.asarray(probe_indices, dtype=np.int64), probe_clearance_um):
                return None
    return _geometry_clearances(coordinates, parents, radii, positions, order, probe_indices,
                                probe_clearance_um)


def _geometry_clearances(points_array, parents, radii_array, positions, order,
                         probe_indices, probe_clearance_um):
    children = np.flatnonzero(parents >= 0)
    counts = np.bincount(parents[children], minlength=len(points_array))
    isolated = np.flatnonzero((parents == -1) & (counts == 0))
    starts = np.concatenate((points_array[parents[children]], points_array[isolated]))
    ends = np.concatenate((points_array[children], points_array[isolated]))
    maximum_radii = np.concatenate((
        np.maximum(radii_array[parents[children]], radii_array[children]), radii_array[isolated],
    ))
    if not len(starts):
        raise ValueError('No SWC geometry')
    delta = ends - starts
    length2 = np.einsum('ij,ij->i', delta, delta)
    if not np.isfinite(length2).all():
        raise ValueError('Segment geometry exceeds numerical range')
    distances = [None] * len(positions)
    for ordinal, i in enumerate(order):
        numerator = np.einsum('ij,ij->i', positions[i] - starts, delta)
        fraction = np.zeros(len(starts), dtype=float)
        np.divide(numerator, length2, out=fraction, where=length2 > 0)
        np.clip(fraction, 0, 1, out=fraction)
        separation = np.linalg.norm(starts + fraction[:, None] * delta - positions[i], axis=1)
        if not np.isfinite(fraction).all() or not np.isfinite(separation).all():
            raise ValueError('Contact geometry exceeds numerical range')
        distances[i] = float(np.min(separation - maximum_radii))
        if (probe_indices is not None and ordinal + 1 == len(probe_indices)
                and all(distances[j] > probe_clearance_um for j in probe_indices)):
            return None
    return distances
