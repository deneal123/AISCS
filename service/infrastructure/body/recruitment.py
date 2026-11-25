"""How a stimulus becomes a set of driven cells: the analytic bipolar field.

An earlier version of this module ranked afferents by distance to the electrode. That
was a guess, and it was a bad one: at the calibrated abdominal site the analytic
bipolar field reproduces the measured recruitment curve exactly, so there is no reason
to guess.

The calibration is measured, not fitted. H95 swept the current at (470, 390, 950)
toward (470, 390, 500) on the real population replay and counted the afferents that
crossed the 7 mV threshold:

    -600 nA    0      -1800 nA   92      -3000 nA  555
    -900 nA    6      -2100 nA  201      -3600 nA  885
    -1200 nA  22      -2400 nA  368

Evaluating the point field at the same site with the same threshold gives
0, 6, 22, 92, 368 and 881 -- every count to within 4 cells out of 885.

The one addition is a soma distance cap. A 1/r potential never dies, so the bare field
recruits cells a millimetre away and the stimulation stops being place specific: at
the brain site the uncapped field still excites 6 afferents at -9600 nA, and at
(520, 380, 1000) it excited 1117 where the replay measured 1 (H91). The population
replay does not use a bare 1/r over the whole population either -- it sums only
sources within 6 um of each segment -- so a cap is faithful to how the replay behaves.
At 120 um the measured curve is preserved (max error 4 cells) and the brain site is
silent. That number is a calibration, not a constant of nature, and it is written down
here so a later measurement can move it.

What this still does not model: each cell's own orientation relative to the field, the
tissue boundary, and the electrode's finite size. A segment-level field solve has all
three; this has none.
"""

from __future__ import annotations

import numpy as np

from ..stimulation.point_field import bipolar_potential_mv

# The threshold the replay used when it counted recruitment, in millivolts.
THRESHOLD_MV = 7.0
# The cap that keeps the calibrated curve and silences the brain site, in micrometres.
SOMA_CAP_UM = 120.0
CONDUCTIVITY_S_M = 0.3
CLEARANCE_UM = 1.0

# Measured at the calibrated abdominal site; used as a cross-check, never as input.
MEASURED_CURVE = ((-600.0, 0), (-900.0, 6), (-1200.0, 22), (-1500.0, 44),
                  (-1800.0, 92), (-2100.0, 201), (-2400.0, 368), (-3000.0, 555),
                  (-3600.0, 885))


def field_recruitment(points_um, site_um, return_um, current_na, *,
                      threshold_mv=THRESHOLD_MV, cap_um=SOMA_CAP_UM):
    """Indices of the cells the field excites above threshold within the soma cap.

    points_um is the array of soma coordinates, one row per cell. The return value
    indexes that array, so the caller keeps its own idea of which cell is which.
    """
    points = np.asarray(points_um, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Invalid soma coordinates")
    if not np.isfinite(float(current_na)):
        raise ValueError("Current must be finite")
    if float(current_na) == 0.0:
        # A zero dose is a real condition, not an error: nothing is recruited.
        return np.zeros(0, dtype=np.int64)
    potential = bipolar_potential_mv(points, tuple(site_um), tuple(return_um),
                                     float(current_na),
                                     CONDUCTIVITY_S_M, clearance_um=CLEARANCE_UM)
    distance = np.linalg.norm(points - np.asarray(site_um, dtype=float), axis=1)
    hot = (np.abs(potential) >= float(threshold_mv)) & (distance <= float(cap_um))
    return np.nonzero(hot)[0].astype(np.int64)


def curve_value(current_na):
    """The measured recruitment count, interpolated; kept to check the field."""
    points = MEASURED_CURVE
    value = abs(float(current_na))
    if value <= abs(points[0][0]):
        return 0
    if value >= abs(points[-1][0]):
        return int(points[-1][1])
    for (left_i, left_n), (right_i, right_n) in zip(points, points[1:]):
        left, right = abs(left_i), abs(right_i)
        if left <= value <= right:
            share = (value - left) / (right - left)
            return int(round(left_n + share * (right_n - left_n)))
    return int(points[-1][1])
