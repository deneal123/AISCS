"""Ideal point-electrode field in an infinite homogeneous isotropic medium.

Coordinates are micrometres, current nanoamperes, conductivity siemens/metre,
and potential millivolts. This is a benchmark operator, not a tissue model or
an excitation rule. See https://pubmed.ncbi.nlm.nih.gov/22036892/.
"""

from __future__ import annotations

import math

import numpy as np


def _points(value, name: str) -> np.ndarray:
    points = np.asarray(value, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError(f"{name} must be a finite array of three-dimensional points")
    return points


def bipolar_potential_mv(
    points_um,
    source_um,
    return_um,
    current_na: float,
    conductivity_s_m: float,
    *,
    clearance_um: float,
) -> np.ndarray:
    """Potential from equal/opposite signed currents; positive current leaves source.

    The zero potential is at infinity. Reject points inside the explicitly
    specified excluded sphere around either ideal source; no singularity is
    regularized or interpreted as a finite electrode surface.
    """
    points = _points(points_um, "points_um")
    contacts = _points([source_um, return_um], "contacts")
    scalars = (current_na, conductivity_s_m, clearance_um)
    if any(isinstance(value, bool | np.bool_) for value in scalars):
        raise ValueError("Scalar parameters must be real numbers")
    if not all(math.isfinite(value) for value in scalars):
        raise ValueError("Scalar parameters must be finite")
    if conductivity_s_m <= 0 or clearance_um <= 0:
        raise ValueError("Conductivity and clearance must be positive")
    if np.linalg.norm(contacts[0] - contacts[1]) <= 2 * clearance_um:
        raise ValueError("Contact exclusion spheres must not intersect")
    first = np.linalg.norm(points - contacts[0], axis=1)
    second = np.linalg.norm(points - contacts[1], axis=1)
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("Contact distance overflow")
    if (first <= clearance_um).any() or (second <= clearance_um).any():
        raise ValueError("Observation point intersects a contact exclusion sphere")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        result = current_na / (4 * np.pi * conductivity_s_m) * (1 / first - 1 / second)
    if not np.isfinite(result).all():
        raise ValueError("Potential overflow")
    return result


def validate_segment_clearance(starts_um, ends_um, contacts_um, clearance_um, radii_um=None):
    """Reject contact exclusion spheres intersecting any continuous cable segment.

    The larger endpoint radius gives a conservative bound on tapered segments.
    This is a geometric safety check for the ideal point-source model,
    not a finite-electrode or tissue-boundary simulation.
    """
    starts = _points(starts_um, "starts_um")
    ends = _points(ends_um, "ends_um")
    contacts = _points(contacts_um, "contacts_um")
    if starts.shape != ends.shape:
        raise ValueError("Segment endpoints must have matching shapes")
    if (isinstance(clearance_um, bool | np.bool_) or not math.isfinite(clearance_um)
            or clearance_um <= 0):
        raise ValueError("Clearance must be finite and positive")
    radii = None if radii_um is None else np.asarray(radii_um, dtype=np.float64)
    if radii is not None and (
        radii.shape != (len(starts), 2) or not np.isfinite(radii).all() or (radii < 0).any()
    ):
        raise ValueError("Segment endpoint radii must be finite and nonnegative")
    vectors = ends - starts
    lengths_squared = np.einsum("ij,ij->i", vectors, vectors)
    if not np.isfinite(lengths_squared).all() or (lengths_squared <= 0).any():
        raise ValueError("Segments must have finite nonzero lengths")
    for contact in contacts:
        fraction = np.clip(np.einsum("ij,ij->i", contact - starts, vectors) / lengths_squared, 0, 1)
        distance = np.linalg.norm(starts + fraction[:, None] * vectors - contact, axis=1)
        if not np.isfinite(distance).all():
            raise ValueError("Contact distance overflow")
        local_radius = 0 if radii is None else np.maximum(radii[:, 0], radii[:, 1])
        if np.any(distance <= clearance_um + local_radius):
            raise ValueError("Contact exclusion sphere intersects a cable segment")


def cable_curvature_mv_per_um2(potential_mv, spacing_um: float) -> np.ndarray:
    """Centered second difference along a straight uniformly sampled cable.

    This is the extracellular-potential curvature only. It is not a voltage,
    membrane current, threshold, or prediction that a neuron has fired.
    """
    potential = np.asarray(potential_mv, dtype=np.float64)
    if potential.ndim != 1 or len(potential) < 3 or not np.isfinite(potential).all():
        raise ValueError("At least three finite cable potentials are required")
    if isinstance(spacing_um, bool | np.bool_) or not math.isfinite(spacing_um) or spacing_um <= 0:
        raise ValueError("Cable spacing must be finite and positive")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        scale = np.float64(spacing_um) ** 2
        result = (potential[:-2] - 2 * potential[1:-1] + potential[2:]) / scale
    if not np.isfinite(result).all() or not np.isfinite(scale) or scale == 0:
        raise ValueError("Cable curvature overflow")
    return result


def neurite_curvature_mv_per_um2(
    points_um, parents, potential_mv, *, exclude_zero_length=False
) -> tuple[np.ndarray, np.ndarray]:
    """Potential curvature on unbranched SWC vertices with unequal spacing.

    Parent indices are zero-based, with -1 for roots. Bifurcations, roots and
    tips have no unique linear cable neighborhood and are omitted. This purely
    geometric field descriptor does not determine activation or current.
    """
    points = _points(points_um, "points_um")
    parents = np.asarray(parents)
    potential = np.asarray(potential_mv, dtype=np.float64)
    n = len(points)
    if (parents.shape != (n,) or parents.dtype.kind != "i" or potential.shape != (n,)
            or not np.isfinite(potential).all()):
        raise ValueError("Parents and finite potentials must match the vertex count")
    if np.any(parents < -1) or np.any(parents >= n) or np.any(parents == np.arange(n)):
        raise ValueError("Invalid parent index")
    visited = set()
    for node in range(n):
        path = set()
        current = node
        while current != -1 and current not in visited:
            if current in path:
                raise ValueError("Cyclic parent graph")
            path.add(current)
            current = int(parents[current])
        visited.update(path)
    children = np.flatnonzero(parents >= 0)
    counts = np.bincount(parents[children], minlength=n)
    child_of = np.full(n, -1, dtype=np.int64)
    child_of[parents[children]] = children
    indices = np.flatnonzero((parents >= 0) & (counts == 1))
    before = np.linalg.norm(points[indices] - points[parents[indices]], axis=1)
    after = np.linalg.norm(points[child_of[indices]] - points[indices], axis=1)
    if not np.isfinite(before).all() or not np.isfinite(after).all():
        raise ValueError("Cable segment length overflow")
    usable = (before > 0) & (after > 0)
    if not np.all(usable) and not exclude_zero_length:
        raise ValueError("Zero-length cable segment")
    indices, before, after = indices[usable], before[usable], after[usable]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        gradient_before = (potential[indices] - potential[parents[indices]]) / before
        gradient_after = (potential[child_of[indices]] - potential[indices]) / after
        values = 2 * (gradient_after - gradient_before) / (before + after)
    if not np.isfinite(values).all():
        raise ValueError("Cable curvature overflow")
    return indices.astype(np.int64, copy=False), values
