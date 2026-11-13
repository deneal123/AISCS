"""Conservative broad-phase filter for validated cable-contact geometry.

The prefilter only reports a definite clear result. Near-boundary and large
numerical cases must be handled by the unchanged clearance calculation.
"""

from __future__ import annotations

import math

from numba import njit


@njit(cache=False)
def may_intersect_box(points, parents, radii, contacts, probes, clearance):
    """Conservatively enclose each cable by an expanded axis-aligned box."""
    extent = max(1., abs(clearance))
    for vertex in range(len(points)):
        for axis in range(3):
            extent = max(extent, abs(points[vertex, axis]))
        extent = max(extent, abs(radii[vertex]))
    for probe in probes:
        for axis in range(3):
            extent = max(extent, abs(contacts[probe, axis]))
    if not math.isfinite(extent) or extent > 1e5 or clearance < 0:
        return True
    # Axis boxes are a superset of the capsule; the guard expands them further
    # to avoid an exclusion caused by floating-point rounding.
    guard = 1e-9 * (1. + extent)
    for probe in probes:
        for child in range(len(points)):
            parent = parents[child]
            if parent == -1:
                parent = child
            reach = clearance + max(radii[parent], radii[child]) + guard
            inside = True
            for axis in range(3):
                lower = min(points[parent, axis], points[child, axis]) - reach
                upper = max(points[parent, axis], points[child, axis]) + reach
                if contacts[probe, axis] < lower or contacts[probe, axis] > upper:
                    inside = False
                    break
            if inside:
                return True
    return False
