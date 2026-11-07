"""Evaluate an ideal electrode field along an individually verified SWC tree.

The result describes extracellular potential and curvature, not excitation.
Source coordinates are the MaleCNS native 8 nm voxel coordinates. Electrode
coordinates must already be registered in that same frame in micrometres.
"""

from __future__ import annotations

import numpy as np

from service.infrastructure.connectome.morphology import validate_swc_topology
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.stimulation.isolated_roots import validate_isolated_root_arrays
from service.infrastructure.stimulation.point_field import (
    bipolar_potential_mv,
    neurite_curvature_mv_per_um2,
    validate_segment_clearance,
)


def evaluate_swc_field(
    swc: str, source_um, return_um, current_na, conductivity_s_m, *, clearance_um,
    allow_degenerate=False, field_backend="cpu",
):
    """Return field values and interior-vertex curvature without inferring spikes."""
    validate_swc_topology(swc)
    return _evaluate_validated_swc_field(
        swc, source_um, return_um, current_na, conductivity_s_m, clearance_um=clearance_um,
        allow_degenerate=allow_degenerate, field_backend=field_backend,
    )


def _parse_swc_geometry(swc):
    rows = [
        line.split()
        for line in swc.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    ids = [int(row[0]) for row in rows]
    index = {value: position for position, value in enumerate(ids)}
    points = np.asarray([[float(value) * 0.008 for value in row[2:5]] for row in rows])
    parents = np.asarray([index[int(row[6])] if int(row[6]) != -1 else -1 for row in rows])
    radii = np.asarray([float(row[5]) * 0.008 for row in rows])
    return ids, points, parents, radii


def _geometry_from_validated_nodes(nodes):
    ids = list(nodes)
    index = {value: position for position, value in enumerate(ids)}
    points = np.asarray([node[0] for node in nodes.values()])
    parents = np.asarray([index[node[1]] if node[1] != -1 else -1 for node in nodes.values()])
    radii = np.asarray([node[3] for node in nodes.values()])
    return ids, points, parents, radii


def _evaluate_validated_swc_field(
    swc: str, source_um, return_um, current_na, conductivity_s_m, *, clearance_um,
    allow_degenerate=False, field_backend="cpu", potential_override=None, geometry_override=None,
):
    ids, points, parents, radii = geometry_override or _parse_swc_geometry(swc)
    children = np.flatnonzero(parents >= 0)
    if type(allow_degenerate) is not bool:
        raise ValueError("allow_degenerate must be boolean")
    if not isinstance(field_backend, str) or field_backend not in {"cpu", "gpu"}:
        raise ValueError("Unknown field backend")
    if field_backend == "gpu":
        from service.infrastructure.stimulation.point_field_gpu import bipolar_potential_mv_gpu

        calculate = bipolar_potential_mv_gpu
    else:
        calculate = bipolar_potential_mv
    if potential_override is None:
        potential = calculate(
            points, source_um, return_um, current_na, conductivity_s_m, clearance_um=clearance_um
        )
    else:
        potential = np.asarray(potential_override, dtype=float)
        if potential.shape != (len(points),) or not np.isfinite(potential).all():
            raise ValueError('Invalid precomputed field')
    zero = np.linalg.norm(points[children] - points[parents[children]], axis=1) == 0
    if np.any(zero) and not allow_degenerate:
        raise ValueError("Segments must have finite nonzero lengths")
    for child in children[zero]:
        radius = max(radii[child], radii[parents[child]])
        if np.any(np.linalg.norm(np.asarray([source_um, return_um]) - points[child], axis=1)
                  <= clearance_um + radius):
            raise ValueError("Contact exclusion sphere intersects a degenerate cable segment")
    valid_children = children[~zero]
    validate_segment_clearance(
        points[parents[valid_children]], points[valid_children], [source_um, return_um],
        clearance_um,
        np.column_stack((radii[parents[valid_children]], radii[valid_children])),
    )
    validate_isolated_root_arrays(points, radii, parents, [source_um, return_um], clearance_um)
    indices, curvature = neurite_curvature_mv_per_um2(
        points, parents, potential, exclude_zero_length=allow_degenerate
    )
    child_counts = np.bincount(parents[children], minlength=len(points))
    candidates = int(np.count_nonzero((parents >= 0) & (child_counts == 1)))
    return {
        "vertex_ids": np.asarray(ids, dtype=np.int64),
        "points_um": points,
        "potential_mv": potential,
        "curvature_vertex_ids": np.asarray(ids)[indices],
        "curvature_mv_per_um2": curvature,
        "omitted_zero_length_edges": int(zero.sum()),
        "omitted_curvature_vertices": candidates - len(indices),
    }


def evaluate_registered_neuron_field(
    body_id, directories, source_um, return_um, current_na, conductivity_s_m, *, clearance_um,
    allow_degenerate=False, field_backend="cpu",
):
    """Evaluate a verified reconstruction and retain the source identity.

    Contacts are in native MaleCNS micrometres, not body display coordinates.
    No activation, tissue boundaries or anatomical registration are inferred.
    """
    skeleton = read_skeleton(body_id, directories, topology_only=True, include_validated_nodes=True)
    geometry = _geometry_from_validated_nodes(skeleton.pop('validated_nodes'))
    values = _evaluate_validated_swc_field(
        skeleton["swc"],
        source_um,
        return_um,
        current_na,
        conductivity_s_m,
        clearance_um=clearance_um,
        allow_degenerate=allow_degenerate,
        field_backend=field_backend,
        geometry_override=geometry,
    )
    return {
        **values,
        "body_id": skeleton["body_id"],
        "source_sha256": skeleton["sha256"],
        "source_url": skeleton["source"],
        "coordinate_frame": "male-cns-v1.0-native-um",
        "medium": "infinite-homogeneous-isotropic",
        "interpretation": "field-only",
    }
