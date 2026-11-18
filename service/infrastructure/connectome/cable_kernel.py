"""Exact nearest-cable search, compiled with numba.

The reference implementation walks a candidate shortlist per point in numpy,
which costs 115-300 us per synapse pair on real cells: hours for a whole
connectome. This module keeps the reference answer and removes that overhead.

Two paths, both exact:

* a shortlist path over the spatial tree, which is the reference answer
  whenever the nearest cable is unique, and
* the reference chunked scan over the whole cable, used only for points whose
  shortlist minimum is inside the reference tie window, so the non-transitive
  chunked tie resolution of synapse_morphology is reproduced bit for bit.
"""

import numpy as np
from numba import njit


@njit(cache=True, nogil=True, fastmath=False)
def _scan(points, starts, vectors, lengths2, offsets, shortlist, chosen,
          fraction, distance2, ties):
    for row in range(points.shape[0]):
        px, py, pz = points[row, 0], points[row, 1], points[row, 2]
        begin, end = offsets[row], offsets[row + 1]
        best = np.inf
        pick = -1
        pick_fraction = 0.0
        for slot in range(begin, end):
            segment = shortlist[slot]
            dx = px - starts[segment, 0]
            dy = py - starts[segment, 1]
            dz = pz - starts[segment, 2]
            vx = vectors[segment, 0]
            vy = vectors[segment, 1]
            vz = vectors[segment, 2]
            local = (dx * vx + dy * vy + dz * vz) / lengths2[segment]
            if local < 0.0:
                local = 0.0
            elif local > 1.0:
                local = 1.0
            rx = dx - local * vx
            ry = dy - local * vy
            rz = dz - local * vz
            value = rx * rx + ry * ry + rz * rz
            if value < best:
                best = value
                pick = segment
                pick_fraction = local
        tolerance = abs(best) * 1e-12 + 1e-18
        count = 0
        for slot in range(begin, end):
            segment = shortlist[slot]
            dx = px - starts[segment, 0]
            dy = py - starts[segment, 1]
            dz = pz - starts[segment, 2]
            vx = vectors[segment, 0]
            vy = vectors[segment, 1]
            vz = vectors[segment, 2]
            local = (dx * vx + dy * vy + dz * vz) / lengths2[segment]
            if local < 0.0:
                local = 0.0
            elif local > 1.0:
                local = 1.0
            rx = dx - local * vx
            ry = dy - local * vy
            rz = dz - local * vz
            value = rx * rx + ry * ry + rz * rz
            if abs(value - best) <= tolerance:
                count += 1
                if segment < pick:
                    pick = segment
                    pick_fraction = local
        chosen[row] = pick
        fraction[row] = pick_fraction
        distance2[row] = best
        ties[row] = count


@njit(cache=True, nogil=True, fastmath=False)
def _scan_exact(points, starts, vectors, lengths2, rows, chosen, fraction,
                distance2, block=2048):
    """Reproduce the reference chunked search, including its tie resolution.

    The reference re-evaluates the tie window after every block, so a running
    minimum that is later beaten can still have produced an earlier pick. That
    is not transitive and must be reproduced block by block.
    """
    total = starts.shape[0]
    for index in range(rows.shape[0]):
        row = rows[index]
        px, py, pz = points[row, 0], points[row, 1], points[row, 2]
        best = np.inf
        exact = np.inf
        pick = -1
        pick_fraction = 0.0
        for offset in range(0, total, block):
            stop = offset + block
            if stop > total:
                stop = total
            block_min = np.inf
            for segment in range(offset, stop):
                dx = px - starts[segment, 0]
                dy = py - starts[segment, 1]
                dz = pz - starts[segment, 2]
                vx = vectors[segment, 0]
                vy = vectors[segment, 1]
                vz = vectors[segment, 2]
                local = (dx * vx + dy * vy + dz * vz) / lengths2[segment]
                if local < 0.0:
                    local = 0.0
                elif local > 1.0:
                    local = 1.0
                rx = dx - local * vx
                ry = dy - local * vy
                rz = dz - local * vz
                value = rx * rx + ry * ry + rz * rz
                if value < block_min:
                    block_min = value
            if block_min < exact:
                exact = block_min
            tolerance = abs(exact) * 1e-12 + 1e-18
            if not (abs(best - exact) <= tolerance):
                for segment in range(offset, stop):
                    dx = px - starts[segment, 0]
                    dy = py - starts[segment, 1]
                    dz = pz - starts[segment, 2]
                    vx = vectors[segment, 0]
                    vy = vectors[segment, 1]
                    vz = vectors[segment, 2]
                    local = (dx * vx + dy * vy + dz * vz) / lengths2[segment]
                    if local < 0.0:
                        local = 0.0
                    elif local > 1.0:
                        local = 1.0
                    rx = dx - local * vx
                    ry = dy - local * vy
                    rz = dz - local * vz
                    value = rx * rx + ry * ry + rz * rz
                    if abs(value - exact) <= tolerance:
                        pick = segment
                        pick_fraction = local
                        best = value
                        break
        if pick < 0:
            pick = 0
        # rows[index] is the point being resolved: writing at 'index' would
        # overwrite an unrelated point and silently corrupt its synapse.
        chosen[row] = pick
        fraction[row] = pick_fraction
        distance2[row] = best


def shortlist(points, starts, vectors, lengths2, tree, half_max):
    """Build the reference radius and flatten every candidate list."""
    distances, nearest = tree.query(points)
    delta = points - starts[nearest]
    local = np.clip(np.einsum('ij,ij->i', delta, vectors[nearest]) / lengths2[nearest], 0., 1.)
    residual = delta - local[:, None] * vectors[nearest]
    initial = np.einsum('ij,ij->i', residual, residual)
    radius = np.sqrt(initial * (1 + 1e-12) + 1e-18) + half_max
    radius = np.nextafter(radius, np.inf)
    lists = tree.query_ball_point(points, radius)
    counts = np.fromiter((len(item) for item in lists), np.int64, len(lists))
    if not counts.all():
        raise ValueError('Empty cable spatial shortlist')
    offsets = np.zeros(len(counts) + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    flat = np.concatenate([np.asarray(item, dtype=np.int64) for item in lists])
    return distances, nearest, offsets, flat


def nearest_cable(points, ids, starts, radii, vectors, lengths2, tree, half_max):
    """Return (child ids, fractions, distances, radii, tie counts)."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError('Invalid synapse coordinates')
    if len(points) == 0:
        empty = np.zeros(0, dtype=float)
        return (np.zeros(0, dtype=np.int64), empty, empty, empty,
                np.zeros(0, dtype=np.int64))
    distances, nearest, offsets, flat = shortlist(
        points, starts, vectors, lengths2, tree, half_max)
    if not np.isfinite(distances).all() or np.any(nearest >= len(ids)):
        raise ValueError('Synapse coordinates exceed supported geometry range')
    chosen = np.full(len(points), -1, dtype=np.int64)
    fraction = np.zeros(len(points))
    squared = np.zeros(len(points))
    ties = np.zeros(len(points), dtype=np.int64)
    _scan(points, starts, vectors, lengths2, offsets, flat, chosen, fraction,
          squared, ties)
    # A point whose shortlist holds more than one candidate inside the reference
    # tie window must be resolved by the reference itself: the chunked search is
    # not transitive, so a tie that spans 2048-segment blocks can keep an earlier,
    # slightly larger minimum (measured: shortlist said 2049, reference 4097).
    tied = np.flatnonzero(ties > 1)
    if len(tied):
        _scan_exact(points, starts, vectors, lengths2, tied, chosen, fraction,
                    squared)
    if np.any(chosen < 0) or not np.isfinite(squared).all():
        raise ValueError('Non-finite synapse to cable distance')
    return (ids[chosen], fraction, np.sqrt(squared),
            radii[chosen, 0] * (1 - fraction) + radii[chosen, 1] * fraction, ties)