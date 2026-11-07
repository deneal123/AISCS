"""Local geometry evidence from a registered segmentation cutout.

This module does not establish neuronal physiology, validate a skeleton, or
authorize a synapse-to-compartment assignment. A negative result is bounded by
the supplied volume; the cell may connect outside it.
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage


def assess_local_connectivity(labels, *, body_id, source_voxel, target_voxel,
                              origin_voxel, projection_radius_voxels=0):
    """Assess 6-neighbor connectivity between two voxels in an XYZ cutout.

    ``target_voxel`` is a rounded skeleton projection, not an anatomical
    endpoint. Nearby distances are measured to the source component within a
    cube and do not establish an electrical path to that projection.
    """
    if (not isinstance(labels, np.ndarray) or labels.ndim != 3
            or labels.dtype.kind not in 'ui' or not labels.size
            or labels.size > 18_000_000 or np.any(np.asarray(labels.shape) == 0)):
        raise ValueError('Invalid segmentation cutout')
    if type(body_id) is not int or not 0 < body_id < 2**64:
        raise ValueError('Invalid segmentation body ID')
    if type(projection_radius_voxels) is not int or not 0 <= projection_radius_voxels <= 31:
        raise ValueError('Invalid projection search radius')

    def coordinate(value):
        if not isinstance(value, (tuple, list)) or len(value) != 3 or any(
            type(v) is not int or not 0 <= v < 2**31 for v in value
        ):
            raise ValueError('Invalid voxel coordinate')
        return np.asarray(value, dtype=np.int64)

    origin = coordinate(origin_voxel)
    source = coordinate(source_voxel) - origin
    target = coordinate(target_voxel) - origin
    shape = np.asarray(labels.shape)
    if (np.any(source < 0) or np.any(source >= shape)
            or np.any(target < 0) or np.any(target >= shape)):
        raise ValueError('Point outside segmentation cutout')

    source_label = int(labels[tuple(source)])
    target_label = int(labels[tuple(target)])
    result = {
        'body_id': body_id,
        'source_label': source_label,
        'target_label': target_label,
        'source_matches': source_label == body_id,
        'target_matches': target_label == body_id,
        'same_component_in_cutout': False,
        'nearest_source_component_to_target_voxels': None,
        'projection_search_complete': False,
        'connectivity': '6-neighbor',
        'interpretation': 'local geometric evidence; not an electrical or physiological validation',
    }
    if source_label != body_id:
        return result

    components, _ = ndimage.label(
        labels == body_id, structure=ndimage.generate_binary_structure(3, 1)
    )
    source_component = int(components[tuple(source)])
    result['same_component_in_cutout'] = bool(
        source_component and components[tuple(target)] == source_component
    )
    radius = projection_radius_voxels
    lo = np.maximum(target - radius, 0)
    hi = np.minimum(target + radius + 1, shape)
    result['projection_search_complete'] = bool(
        np.all(target - radius >= 0) and np.all(target + radius < shape)
    )
    region = components[tuple(slice(int(a), int(b)) for a, b in zip(lo, hi, strict=True))]
    locations = np.argwhere(region == source_component)
    if locations.size:
        distances = np.linalg.norm(locations + lo - target, axis=1)
        result['nearest_source_component_to_target_voxels'] = float(distances.min())
        if not math.isfinite(result['nearest_source_component_to_target_voxels']):
            raise ValueError('Invalid geometric distance')
    return result
