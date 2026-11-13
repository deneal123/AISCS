"""Experimental conversion of authenticated packed geometry to cable inputs."""

import re

import numpy as np

from service.infrastructure.connectome.morphology_repository import BASE


def cached_cable_inputs(entry, *, body_id, expected_sha256):
    """Convert one independently authenticated cache entry, preserving SWC order.

    The caller must authenticate the manifest, source index and chunk before
    calling. A matching source digest alone is not proof that an entry is
    authentic. This function does not assert current SWC file availability.
    """
    if (type(body_id) is not int or body_id <= 0 or not isinstance(expected_sha256, str)
            or not re.fullmatch('[0-9a-f]{64}', expected_sha256)
            or not isinstance(entry, dict) or not isinstance(entry.get('skeleton'), dict)):
        raise ValueError('Invalid authenticated geometry identity')
    skeleton = entry['skeleton']
    if (skeleton.get('body_id') != str(body_id) or skeleton.get('sha256') != expected_sha256
            or skeleton.get('source') != f'{BASE}{body_id}.swc'
            or skeleton.get('source_units') != '8 nm'):
        raise ValueError('Cached geometry source mismatch')
    geometry = entry.get('geometry')
    if not isinstance(geometry, tuple | list) or len(geometry) != 4:
        raise ValueError('Invalid cached geometry arrays')
    ids, points, parents, radii = (np.asarray(value) for value in geometry)
    n = len(ids) if ids.ndim == 1 else 0
    if (not n or ids.dtype.kind not in 'iu' or parents.dtype.kind not in 'iu'
            or points.dtype != np.float64 or radii.dtype != np.float64
            or points.shape != (n, 3) or parents.shape != (n,) or radii.shape != (n,)
            or np.any(ids <= 0) or len(np.unique(ids)) != n
            or np.any(parents < -1) or np.any(parents >= n)
            or not np.isfinite(points).all() or not np.isfinite(radii).all()
            or np.any(radii < 0)):
        raise ValueError('Invalid cached geometry arrays')
    components = int(np.count_nonzero(parents == -1))
    if not components:
        raise ValueError('Cached geometry has no root')
    # Validate all components, including cycles disconnected from a root.
    state = bytearray(n)
    parent_indices = parents.tolist()
    for index in range(n):
        current, path = index, []
        while current != -1 and state[current] == 0:
            state[current] = 1
            path.append(current)
            current = parent_indices[current]
        if current != -1 and state[current] == 1:
            raise ValueError('Cyclic cached geometry')
        for node in path:
            state[node] = 2
    nodes = {int(node): (points[index], float(radii[index])) for index, node in enumerate(ids)}
    edges = [(int(ids[index]), int(ids[parent])) for index, parent in enumerate(parents)
             if parent != -1]
    return nodes, edges, components
