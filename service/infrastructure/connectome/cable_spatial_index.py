"""Experimental exact spatial shortlist for nearest cable centreline queries."""

import numpy as np
from scipy.spatial import cKDTree


class CableSpatialIndex:
    """Index already validated segments; returned matches remain geometric candidates."""

    def __init__(self, prepared):
        ids, starts, radii, vectors, lengths2 = prepared
        self.ids = np.asarray(ids)
        self.starts = np.asarray(starts, dtype=float)
        self.radii = np.asarray(radii, dtype=float)
        self.vectors = np.asarray(vectors, dtype=float)
        self.lengths2 = np.asarray(lengths2, dtype=float)
        n = len(self.ids)
        if (n < 1 or self.ids.shape != (n,) or self.ids.dtype.kind not in 'iu'
                or np.any(np.diff(self.ids) <= 0)
                or self.starts.shape != (n, 3) or self.vectors.shape != (n, 3)
                or self.radii.shape != (n, 2) or self.lengths2.shape != (n,)
                or not all(np.isfinite(a).all() for a in
                           (self.starts, self.vectors, self.radii, self.lengths2))
                or np.any(self.radii <= 0) or np.any(self.lengths2 <= 0)
                or not np.allclose(self.lengths2,
                    np.einsum('ij,ij->i', self.vectors, self.vectors), rtol=1e-12, atol=1e-18)):
            raise ValueError('Invalid indexed cable geometry')
        self.midpoints = self.starts + self.vectors * .5
        self.half_max = float(np.sqrt(self.lengths2).max() * .5)
        self.tree = cKDTree(self.midpoints)

    def _distances(self, point, indices):
        delta = point - self.starts[indices]
        fractions = np.clip(np.einsum('ij,ij->i', delta, self.vectors[indices])
                            / self.lengths2[indices], 0., 1.)
        residual = delta - fractions[:, None] * self.vectors[indices]
        return np.einsum('ij,ij->i', residual, residual), fractions

    def query(self, points_um):
        points = np.asarray(points_um, dtype=float)
        if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
            raise ValueError('Invalid synapse coordinates')
        identifiers, fractions, distances, local_radii = [], [], [], []
        tie_points, tie_positions = [], []
        tree_distances, nearest_indices = self.tree.query(points)
        if (not np.isfinite(tree_distances).all()
                or np.any(nearest_indices >= len(self.ids))):
            raise ValueError('Synapse coordinates exceed supported geometry range')
        for point, nearest in zip(points, nearest_indices, strict=True):
            initial, _ = self._distances(point, np.array([int(nearest)]))
            # Any closer segment must have its midpoint within this radius.
            # Include the existing tie tolerance and a floating-point margin.
            radius = np.sqrt(initial[0] * (1 + 1e-12) + 1e-18) + self.half_max
            radius = np.nextafter(radius, np.inf)
            candidates = np.asarray(sorted(self.tree.query_ball_point(point, radius)), dtype=int)
            if not len(candidates):
                raise ValueError('Empty cable spatial shortlist')
            squared, positions = self._distances(point, candidates)
            minimum = squared.min()
            ties = np.flatnonzero(np.isclose(squared, minimum, rtol=1e-12, atol=1e-18))
            if len(ties) > 1:
                # Resolve ties together below using the established chunked search.
                tie_positions.append(len(identifiers))
                tie_points.append(point)
                identifiers.append(None)
                fractions.append(None)
                distances.append(None)
                local_radii.append(None)
                continue
            pick = int(ties[0])
            index, fraction = candidates[pick], positions[pick]
            identifiers.append(int(self.ids[index]))
            fractions.append(float(fraction))
            distances.append(float(np.sqrt(squared[pick])))
            local_radii.append(float(self.radii[index, 0] * (1 - fraction)
                                     + self.radii[index, 1] * fraction))
        if tie_points:
            from .synapse_morphology import _nearest_prepared_segments

            original = _nearest_prepared_segments(
                (self.ids, self.starts, self.radii, self.vectors, self.lengths2),
                np.asarray(tie_points),
            )
            for row, position in enumerate(tie_positions):
                identifiers[position] = original['child_node_ids'][row]
                fractions[position] = original['segment_fractions'][row]
                distances[position] = original['centerline_distances_um'][row]
                local_radii[position] = original['interpolated_swc_radii_um'][row]
        return {'child_node_ids': identifiers, 'segment_fractions': fractions,
                'centerline_distances_um': distances, 'interpolated_swc_radii_um': local_radii,
                'coordinate_frame': 'MaleCNS native EM, micrometres',
                'interpretation': 'nearest centerline candidates; '
                                  'not validated synaptic compartments'}
