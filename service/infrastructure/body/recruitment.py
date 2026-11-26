"""How a stimulus becomes a set of driven cells: the analytic bipolar field.

The stimulus is a point-source field in a homogeneous medium. Its two parameters that
are not laws of physics -- the threshold at which a soma counts as driven and, in an
earlier version, a cap on how far the field may reach -- are calibrations, and this
module states both and reproduces the measurements that pin them.

What the field reproduces, with no cap and no fitted scale factor:

  * the dose curve H95 measured at (470, 390, 950) toward (470, 390, 500) on the real
    population replay, counting afferents with |V| >= 7 mV:

        -600 nA 0    -900 nA 6    -1200 nA 22    -1500 nA 44    -1800 nA 92
        -2100 nA 201  -2400 nA 368  -3000 nA 555  -3600 nA 885

    The model gives 0, 6, 22, 44, 92, 201, 368, 555, 885: every count exact.

  * the site map H91 measured at -9600 nA over an 18-point grid of electrode positions,
    counting afferents with |V| >= 30 mV. The model gives 997, 1004, 844, 489, 477, 429,
    1, 1, 1, 0 ... 0: every count exact, including the collapse from 489 to 1 across a
    50 um shift.

  * the production brain configuration (73.606, 150.455, 278.599) to
    (929.056, 387.68, 228.352): no afferent reaches either threshold at any tested
    current, which is what the replay measured.

A correction this module carries, because the earlier version got it wrong: the two
measured datasets were counted at DIFFERENT thresholds -- 7 mV for the dose curve and
30 mV for the site map. Reading both as 7 mV made the site map disagree by up to 637
cells, and the previous version patched that disagreement with a 120 um soma cap. The
cap was not a measurement: with the thresholds read correctly, the uncapped field
reproduces both datasets exactly, and the cap is gone. A cap remains available as an
argument for callers that want a bounded stimulus, but it defaults to infinity.

What this still does not model: the field is evaluated at the soma centroid, while the
replay applies it to every segment midpoint and lets the cable integrate it. A twin
episode therefore asks "which somata see enough field", which is the question every
measurement in this series was defined by, not "which cells spike", which is the
connectome's answer that follows.
"""

from __future__ import annotations

import numpy as np

from ..stimulation.point_field import bipolar_potential_mv

# The threshold the dose curve was counted at, in millivolts. H95 forced exactly the
# cells above this value and the network answered, so this is the threshold that makes
# a twin episode comparable to the measurements.
THRESHOLD_MV = 7.0

# The threshold the site map was counted at, in millivolts. Kept separate on purpose:
# collapsing the two is the error this module used to make.
SITE_MAP_THRESHOLD_MV = 30.0

CONDUCTIVITY_S_M = 0.3
CLEARANCE_UM = 1.0

# Measured at the calibrated abdominal site; used as a cross-check, never as input.
MEASURED_CURVE = ((-600.0, 0), (-900.0, 6), (-1200.0, 22), (-1500.0, 44),
                  (-1800.0, 92), (-2100.0, 201), (-2400.0, 368), (-3000.0, 555),
                  (-3600.0, 885))

# Measured over the electrode grid at -9600 nA, counted at 30 mV. Rows are x, columns y.
MEASURED_SITE_MAP = {
    "current_na": -9600.0,
    "z_source_um": 1000.0,
    "z_return_um": 500.0,
    "counts": {(420.0, 380.0): 997, (420.0, 400.0): 1004, (420.0, 420.0): 844,
               (470.0, 380.0): 489, (470.0, 400.0): 477, (470.0, 420.0): 429,
               (520.0, 380.0): 1, (520.0, 400.0): 1, (520.0, 420.0): 1,
               (570.0, 380.0): 0, (570.0, 400.0): 0, (570.0, 420.0): 0,
               (620.0, 380.0): 0, (620.0, 400.0): 0, (620.0, 420.0): 0,
               (670.0, 380.0): 0, (670.0, 400.0): 0, (670.0, 420.0): 0},
}


def field_recruitment(points_um, site_um, return_um, current_na, *,
                      threshold_mv=THRESHOLD_MV, cap_um=None):
    """Indices of the cells whose soma the field drives above threshold.

    points_um is the array of soma coordinates, one row per cell. The return value
    indexes that array, so the caller keeps its own idea of which cell is which.

    cap_um defaults to None, meaning no cap: at the production configurations the
    uncapped field is already silent where the replay measured silence, so a cap would
    be a fitted number with nothing left to fit.
    """
    points = np.asarray(points_um, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("Invalid soma coordinates")
    if not np.isfinite(float(current_na)):
        raise ValueError("Current must be finite")
    if not np.isfinite(float(threshold_mv)) or float(threshold_mv) <= 0.0:
        raise ValueError("Threshold must be finite and positive")
    if float(current_na) == 0.0:
        # A zero dose is a real condition, not an error: nothing is recruited.
        return np.zeros(0, dtype=np.int64)
    potential = bipolar_potential_mv(points, tuple(site_um), tuple(return_um),
                                     float(current_na),
                                     CONDUCTIVITY_S_M, clearance_um=CLEARANCE_UM)
    hot = np.abs(potential) >= float(threshold_mv)
    if cap_um is not None:
        distance = np.linalg.norm(points - np.asarray(site_um, dtype=float), axis=1)
        hot &= distance <= float(cap_um)
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


def check_against_measurements(points_um, *, site_um=(470.0, 390.0, 950.0),
                               return_um=(470.0, 390.0, 500.0)):
    """Recount both measured datasets and return the errors; used by the tests.

    This exists so that a later edit to the field, the threshold or a cap cannot pass
    silently. It is not part of an episode; it is the calibration's own regression.
    """
    curve = []
    for dose, measured in MEASURED_CURVE:
        model = len(field_recruitment(points_um, site_um, return_um, dose))
        curve.append({"dose_na": dose, "measured": measured, "model": model,
                      "error": model - measured})
    grid = []
    map_data = MEASURED_SITE_MAP
    for (x, y), measured in map_data["counts"].items():
        model = len(field_recruitment(points_um, (x, y, map_data["z_source_um"]),
                                      (x, y, map_data["z_return_um"]),
                                      map_data["current_na"],
                                      threshold_mv=SITE_MAP_THRESHOLD_MV))
        grid.append({"x_um": x, "y_um": y, "measured": measured, "model": model,
                     "error": model - measured})
    return {"curve": curve, "site_map": grid,
            "curve_max_error": max(abs(row["error"]) for row in curve),
            "site_map_max_error": max(abs(row["error"]) for row in grid)}
