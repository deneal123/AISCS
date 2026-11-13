"""Precompute an equivalent nodal projection for point-source recording.

This is a building block for a future cell-major streaming kernel. It does not
perform a simulation, model volume conduction, or replace recording validation.
"""

import numpy as np


def nodal_recording_projection(parents, conductances, segment_nodes,
                               segment_coefficients, field_current_na):
    """Return weights and field factor for the existing membrane-current equation.

    The result maps node voltages to the same weighted segment-current sum as
    ``hines_kernel.batched``: ``weights @ voltages + factor * stimulus``.
    Segment coefficients must already encode electrode geometry and units. The
    kernel's initial-sample convention is the caller's responsibility.
    """
    parent = np.asarray(parents)
    segment = np.asarray(segment_nodes)
    try:
        conductance = np.asarray(conductances, dtype=np.float64)
        coefficient = np.asarray(segment_coefficients, dtype=np.float64)
        field = np.asarray(field_current_na, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError('Invalid recording projection') from exc
    if (parent.ndim != 1 or parent.size < 1 or parent.dtype.kind not in 'iu'
            or parent[0] != -1 or conductance.shape != parent.shape
            or segment.ndim != 1 or segment.size < 1 or segment.dtype.kind not in 'iu'
            or coefficient.shape != segment.shape or field.shape != segment.shape
            or np.any(parent[1:] < 0) or np.any(parent[1:] >= np.arange(1, len(parent)))
            or np.any(segment < 0) or np.any(segment >= len(parent))
            or len(np.unique(segment)) != len(segment)
            or not all(np.isfinite(item).all() for item in (conductance, coefficient, field))
            or np.any(conductance < 0)):
        raise ValueError('Invalid recording projection')

    # Each axial edge contributes to the two endpoint voltages. Nodes without
    # membrane segments have zero recording coefficient but remain in the tree.
    node_coeff = np.zeros(len(parent), dtype=np.float64)
    node_coeff[segment] = coefficient
    edge_weight = conductance[1:] * (node_coeff[parent[1:]] - node_coeff[1:])
    weights = np.zeros(len(parent), dtype=np.float64)
    weights[1:] = edge_weight
    np.add.at(weights, parent[1:], -edge_weight)
    field_factor = float(coefficient @ field)
    if not np.isfinite(weights).all() or not np.isfinite(field_factor):
        raise ValueError('Non-finite recording projection')
    return weights, field_factor
