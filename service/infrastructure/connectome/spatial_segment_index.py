"""Exact broad-phase candidates for point-to-segment distance queries.

Each segment lies inside a ball centered on its midpoint with radius equal to
half its length. An exact distance to any one segment supplies an upper bound;
the triangle inequality then bounds all other possible nearest segments. The
final projection and tie-breaking must still be performed on returned indices.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.spatial import cKDTree


class SegmentCandidateIndex:
    def __init__(self, starts, vectors, length2):
        self.starts = np.asarray(starts, dtype=float)
        self.vectors = np.asarray(vectors, dtype=float)
        self.length2 = np.asarray(length2, dtype=float)
        if (self.starts.ndim != 2 or self.starts.shape[1:] != (3,)
                or self.vectors.shape != self.starts.shape
                or self.length2.shape != (len(self.starts),) or not len(self.starts)
                or not np.isfinite(self.starts).all() or not np.isfinite(self.vectors).all()
                or not np.isfinite(self.length2).all() or np.any(self.length2 <= 0)):
            raise ValueError('Invalid segments')
        with np.errstate(over='ignore', invalid='ignore'):
            expected_length2 = np.einsum('ij,ij->i', self.vectors, self.vectors)
            self.midpoints = self.starts + self.vectors * .5
            half_lengths = np.sqrt(self.length2) * .5
        if (not np.array_equal(expected_length2, self.length2)
                or not np.isfinite(self.midpoints).all() or not np.isfinite(half_lengths).all()):
            raise ValueError('Invalid or non-finite segment bounds')
        self.tree = cKDTree(self.midpoints)
        _, bins = np.frexp(half_lengths)
        self.groups = []
        for number in np.unique(bins):
            indices = np.flatnonzero(bins == number)
            self.groups.append((indices, float(half_lengths[indices].max()),
                                float(np.max(np.abs(self.midpoints[indices]))),
                                cKDTree(self.midpoints[indices])))

    def candidates(self, point):
        point = np.asarray(point, dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError('Invalid query point')
        _, selected = self.tree.query(point)
        if not np.isfinite(selected) or selected >= len(self.starts):
            raise ValueError('Non-finite query distance')
        index = int(selected)
        with np.errstate(over='ignore', invalid='ignore'):
            delta = point - self.starts[index]
            fraction = np.clip(np.dot(delta, self.vectors[index]) / self.length2[index], 0, 1)
            residual = delta - fraction * self.vectors[index]
            upper2 = float(np.dot(residual, residual))
        if not math.isfinite(upper2):
            raise ValueError('Non-finite query distance')
        # Match the exhaustive comparator's squared-distance tie tolerance.
        bound = math.sqrt(upper2 * (1 + 1e-12) + 1e-18)
        if not math.isfinite(bound):
            raise ValueError('Non-finite query distance')
        selected_indices = []
        for indices, half_length, magnitude, tree in self.groups:
            radius = bound + half_length
            # Protect the triangle-inequality bound from floating-point rounding.
            radius += 32 * np.finfo(float).eps * (
                np.max(np.abs(point)) + magnitude + radius + 1)
            if not math.isfinite(radius):
                raise ValueError('Non-finite query distance')
            matches = tree.query_ball_point(point, np.nextafter(radius, np.inf))
            selected_indices.extend(indices[matches].tolist())
        if not selected_indices:
            raise ValueError('Segment candidate index returned no candidates')
        return np.asarray(sorted(selected_indices), dtype=np.int64)
