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
        from .cable_kernel import nearest_cable

        identifiers, fractions, distances, local_radii, _ties = nearest_cable(
            points, self.ids, self.starts, self.radii, self.vectors,
            self.lengths2, self.tree, self.half_max)
        return {"child_node_ids": identifiers.tolist(),
                "segment_fractions": fractions.tolist(),
                "centerline_distances_um": distances.tolist(),
                "interpolated_swc_radii_um": local_radii.tolist(),
                "coordinate_frame": "MaleCNS native EM, micrometres",
                "interpretation": "nearest centerline candidates; "
                                  "not validated synaptic compartments"}