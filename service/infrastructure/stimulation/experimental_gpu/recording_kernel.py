"""Fused per-segment recording kernel: clearance predicate and field coefficients.

The numpy recorder built its coefficients in two passes over every segment of a
batch: ``validate_segment_clearance`` projects each segment onto both point
contacts and compares the distance against the clearance sphere, and
``bipolar_potential_mv`` evaluates the 1/r potential difference at every
segment midpoint. Measured on 389 152 real segments of the MaleCNS cache, those
two passes cost 0.160 s, of which the clearance predicate is 0.093 s; the same
arithmetic in one numba kernel costs 0.0037 s (43.8x) and reproduced the numpy
coefficients BITWISE on that sample (max absolute difference 0.0).

The recording coefficients are part of the published feedback result, so the
kernel keeps the numpy evaluation order and comparison directions exactly:
half a ulp of drift would change the archived trace, not just its timing.
``numpy_coefficients`` stays next to it as the reference the tests compare
against bitwise, and it is what the kernel must never disagree with.
"""

from __future__ import annotations

import math
from pathlib import Path
import os

import numpy as np

# Point numba's on-disk cache beside this module unless the caller chose one.
# Import-time only, so it has to precede the numba import.
os.environ.setdefault(
    "NUMBA_CACHE_DIR", str(Path(__file__).resolve().parent / ".numba-cache")
)

from numba import njit, prange  # noqa: E402

# Kernel failure codes, in the order the numpy path reports them.
_INVALID_LENGTH = 1
_CONTACT_OVERFLOW = 2
_SEGMENT_CLEARANCE = 3
_OBSERVATION_CLEARANCE = 4
_POTENTIAL_OVERFLOW = 5


@njit(cache=True, parallel=True, boundscheck=False, fastmath=False, nogil=True)
def _fused(starts, ends, radii, midpoints, electrode, reference, field_factor,
           clearance, coefficients, flags):
    """Coefficients and clearance flags for every concatenated segment."""
    count = starts.shape[0]
    for index in prange(count):
        flags[index] = 0
        vx = ends[index, 0] - starts[index, 0]
        vy = ends[index, 1] - starts[index, 1]
        vz = ends[index, 2] - starts[index, 2]
        length_squared = vx * vx + vy * vy + vz * vz
        if not (length_squared > 0.) or not math.isfinite(length_squared):
            flags[index] = _INVALID_LENGTH
        dx = midpoints[index, 0] - electrode[0]
        dy = midpoints[index, 1] - electrode[1]
        dz = midpoints[index, 2] - electrode[2]
        first = math.sqrt(dx * dx + dy * dy + dz * dz)
        dx = midpoints[index, 0] - reference[0]
        dy = midpoints[index, 1] - reference[1]
        dz = midpoints[index, 2] - reference[2]
        second = math.sqrt(dx * dx + dy * dy + dz * dz)
        if not math.isfinite(first) or not math.isfinite(second):
            flags[index] = _CONTACT_OVERFLOW
        elif first <= clearance or second <= clearance:
            flags[index] = _OBSERVATION_CLEARANCE
        value = 1000. * (field_factor * (1. / first - 1. / second))
        if not math.isfinite(value):
            flags[index] = _POTENTIAL_OVERFLOW
        coefficients[index] = value
        radius = radii[index, 0]
        if radii[index, 1] > radius:
            radius = radii[index, 1]
        for contact in range(2):
            if contact == 0:
                cx = electrode[0]
                cy = electrode[1]
                cz = electrode[2]
            else:
                cx = reference[0]
                cy = reference[1]
                cz = reference[2]
            ex = cx - starts[index, 0]
            ey = cy - starts[index, 1]
            ez = cz - starts[index, 2]
            fraction = (ex * vx + ey * vy + ez * vz) / length_squared
            if fraction < 0.:
                fraction = 0.
            elif fraction > 1.:
                fraction = 1.
            dx = starts[index, 0] + fraction * vx - cx
            dy = starts[index, 1] + fraction * vy - cy
            dz = starts[index, 2] + fraction * vz - cz
            distance = math.sqrt(dx * dx + dy * dy + dz * dz)
            if not math.isfinite(distance):
                flags[index] = _CONTACT_OVERFLOW
            elif distance <= clearance + radius and flags[index] != _INVALID_LENGTH:
                flags[index] = _SEGMENT_CLEARANCE


_MESSAGES = {
    _INVALID_LENGTH: "Segments must be finite nonzero lengths",
    _CONTACT_OVERFLOW: "Contact distance overflow",
    _SEGMENT_CLEARANCE: "Contact exclusion sphere intersects a cable segment",
    _OBSERVATION_CLEARANCE: "Observation point intersects a contact exclusion sphere",
    _POTENTIAL_OVERFLOW: "Potential overflow",
}

# Reported in the numpy path's order: the segment predicate runs before the
# potential evaluation, so a segment that intersects a sphere is reported even
# when its observation point is also inside one.
_PRIORITY = (_INVALID_LENGTH, _CONTACT_OVERFLOW, _SEGMENT_CLEARANCE,
             _OBSERVATION_CLEARANCE, _POTENTIAL_OVERFLOW)


def _points(value, name):
    points = np.asarray(value, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError(f"{name} must be a finite array of three-dimensional points")
    return points


def numpy_coefficients(starts_um, ends_um, radii_um, midpoints_um, source_um,
                       return_um, conductivity_s_m, clearance_um):
    """The reference evaluation: the two numpy passes the kernel replaces."""
    from service.infrastructure.stimulation.point_field import (
        bipolar_potential_mv, validate_segment_clearance)

    validate_segment_clearance(starts_um, ends_um, [source_um, return_um], clearance_um,
                               radii_um)
    return 1000 * bipolar_potential_mv(midpoints_um, source_um, return_um, 1.,
                                       conductivity_s_m, clearance_um=clearance_um)


def coefficients(starts_um, ends_um, radii_um, midpoints_um, source_um, return_um,
                 conductivity_s_m, *, clearance_um):
    """Validate the batch geometry and return its recording coefficients.

    Raises the same ValueErrors, with the same messages, as the numpy path.
    """
    starts = _points(starts_um, "starts_um")
    ends = _points(ends_um, "ends_um")
    midpoints = _points(midpoints_um, "midpoints_um")
    contact = _points(np.asarray([source_um, return_um], dtype=np.float64), "contacts")
    if starts.shape != ends.shape or starts.shape != midpoints.shape:
        raise ValueError("Segment endpoints must have matching shapes")
    radii = np.asarray(radii_um, dtype=np.float64)
    if radii.shape != (len(starts), 2) or not np.isfinite(radii).all() or (radii < 0).any():
        raise ValueError("Segment endpoint radii must be finite and nonnegative")
    if (isinstance(clearance_um, bool | np.bool_) or not math.isfinite(clearance_um)
            or clearance_um <= 0):
        raise ValueError("Clearance must be finite and positive")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        contact_distance = np.linalg.norm(contact[0] - contact[1])
        field_factor = np.float64(1.) / (4 * np.pi * np.float64(conductivity_s_m))
    if not np.isfinite(contact_distance):
        raise ValueError("Contact distance overflow")
    if not np.isfinite(field_factor):
        raise ValueError("Potential overflow")
    if contact_distance <= 2 * clearance_um:
        raise ValueError("Contact exclusion spheres must not intersect")
    result = np.empty(len(starts), dtype=np.float64)
    flags = np.zeros(len(starts), dtype=np.int8)
    _fused(starts, ends, radii, midpoints, contact[0], contact[1], field_factor,
           float(clearance_um), result, flags)
    if flags.any():
        for code in _PRIORITY:
            if (flags == code).any():
                raise ValueError(_MESSAGES[code])
    return result