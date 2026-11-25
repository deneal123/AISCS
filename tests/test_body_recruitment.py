"""The field turns a site and a current into cells, and the measured curve is the check.

The numbers in these tests are the measured ones: the dose curve was counted on the
real population replay (H95), and the brain site was measured silent at every current
up to -14400 nA. A recruitment model that fails them is wrong regardless of how
plausible it looks.
"""

import numpy as np
import pytest

from service.infrastructure.body.recruitment import (SOMA_CAP_UM, curve_value,
                                                     field_recruitment)

SITE = (470.0, 390.0, 950.0)
RETURN = (470.0, 390.0, 500.0)
BRAIN_SITE = (419.328, 379.488, 359.92)
BRAIN_RETURN = (444.8, 417.2, 466.9)


def _cloud(count, extent_um, seed=0):
    """A cube of somas around the site, dense enough for the field to reach."""
    generator = np.random.default_rng(seed)
    return np.asarray(SITE) + generator.uniform(-extent_um, extent_um, size=(count, 3))


def test_a_zero_current_recruits_nothing():
    points = _cloud(500, 200.0)
    assert field_recruitment(points, SITE, RETURN, 0.0).size == 0


def test_more_current_recruits_more_cells_monotonically():
    points = _cloud(2000, 300.0)
    counts = [field_recruitment(points, SITE, RETURN, current).size
              for current in (-600.0, -1200.0, -2400.0, -3600.0)]
    assert counts == sorted(counts)
    assert counts[0] <= counts[-1]
    assert counts[0] == 0


def test_the_brain_site_stays_silent_at_every_current():
    """Measured: -600 to -14400 nA at the combat electrode produced no afferent."""
    points = _cloud(2000, 300.0)
    for current in (-1200.0, -3600.0, -9600.0, -14400.0):
        assert field_recruitment(points, BRAIN_SITE, BRAIN_RETURN, current).size == 0


def test_the_soma_cap_bounds_recruitment_by_geometry():
    points = _cloud(3000, 400.0)
    chosen = field_recruitment(points, SITE, RETURN, -9600.0)
    distance = np.linalg.norm(points[chosen] - np.asarray(SITE), axis=1)
    assert chosen.size > 0
    assert distance.max() <= SOMA_CAP_UM


def test_the_cap_is_what_makes_far_sites_selective():
    """Without the cap the same current reaches cells a millimetre away."""
    points = _cloud(3000, 400.0)
    with_cap = field_recruitment(points, SITE, RETURN, -9600.0, cap_um=SOMA_CAP_UM)
    without = field_recruitment(points, SITE, RETURN, -9600.0, cap_um=10000.0)
    assert without.size > with_cap.size


def test_the_measured_curve_is_interpolated_and_held_at_its_ends():
    assert curve_value(0.0) == 0
    assert curve_value(-300.0) == 0
    assert curve_value(-900.0) == 6
    assert curve_value(-1200.0) == 22
    assert curve_value(-1350.0) == 33
    # Held, not extrapolated: nothing above 3600 nA was measured.
    assert curve_value(-9600.0) == 885


def test_invalid_input_is_refused():
    with pytest.raises(ValueError):
        field_recruitment(np.zeros((4, 2)), SITE, RETURN, -1200.0)
    with pytest.raises(ValueError):
        field_recruitment(_cloud(10, 50.0), SITE, RETURN, float("nan"))
