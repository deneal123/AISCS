"""The stimulus field must reproduce the measurements it was calibrated on.

Both datasets were measured on the real population replay and are reproduced here by
recounting them through the field, so an edit to the field or to a threshold fails a
test rather than a later experiment.
"""

import csv
from pathlib import Path

import numpy as np
import pytest

from service.infrastructure.body import recruitment

LABELS = Path("/in2/nociception-dataset/labels.csv")
FALLBACK = Path("/work/connectome-routing-20261028/nociception-dataset/labels.csv")


def _somas():
    """The 1145 abdominal afferent soma centroids, as the nociception series used them."""
    path = LABELS if LABELS.exists() else FALLBACK
    if not path.exists():
        pytest.skip("afferent soma table is not mounted", allow_module_level=True)
    points = []
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            points.append((float(row["x_um"]), float(row["y_um"]), float(row["z_um"])))
    return np.asarray(points, dtype=float)


def test_the_dose_curve_is_reproduced_exactly():
    points = _somas()
    errors = []
    for dose, measured in recruitment.MEASURED_CURVE:
        model = len(recruitment.field_recruitment(
            points, (470.0, 390.0, 950.0), (470.0, 390.0, 500.0), dose))
        errors.append(abs(model - measured))
    assert max(errors) == 0


def test_the_site_map_is_reproduced_exactly_at_its_own_threshold():
    points = _somas()
    errors = []
    for (x, y), measured in recruitment.MEASURED_SITE_MAP["counts"].items():
        model = len(recruitment.field_recruitment(
            points, (x, y, 1000.0), (x, y, 500.0), -9600.0,
            threshold_mv=recruitment.SITE_MAP_THRESHOLD_MV))
        errors.append(abs(model - measured))
    assert max(errors) == 0


def test_the_two_thresholds_are_not_the_same_number():
    # The error this module used to make: reading the site map at the dose curve's
    # threshold made it disagree by hundreds of cells, and a 120 um cap was added to
    # hide the disagreement. Both datasets are reproduced with no cap, so the thresholds
    # stay separate and the cap stays off.
    assert recruitment.THRESHOLD_MV != recruitment.SITE_MAP_THRESHOLD_MV
    points = _somas()
    wrong = len(recruitment.field_recruitment(points, (470.0, 380.0, 1000.0),
                                              (470.0, 380.0, 500.0), -9600.0,
                                              threshold_mv=7.0))
    right = len(recruitment.field_recruitment(points, (470.0, 380.0, 1000.0),
                                              (470.0, 380.0, 500.0), -9600.0,
                                              threshold_mv=30.0))
    assert wrong > 1000 > right


def test_the_production_brain_configuration_drives_no_afferent():
    points = _somas()
    source = (73.606, 150.455, 278.599)
    contact = (929.056, 387.68, 228.352)
    for dose in (-4800.0, -9600.0, -14400.0):
        assert len(recruitment.field_recruitment(points, source, contact, dose)) == 0


def test_a_zero_dose_recruits_nothing_and_is_not_an_error():
    points = _somas()
    assert len(recruitment.field_recruitment(points, (470.0, 390.0, 950.0),
                                             (470.0, 390.0, 500.0), 0.0)) == 0


def test_recruitment_is_monotonic_in_dose():
    points = _somas()
    counts = [len(recruitment.field_recruitment(points, (470.0, 390.0, 950.0),
                                                (470.0, 390.0, 500.0), dose))
              for dose in (0.0, -600.0, -1200.0, -2400.0, -3600.0, -9600.0)]
    assert counts == sorted(counts)
    assert counts[0] == 0 and counts[-1] > 0


def test_the_cap_is_off_by_default_and_still_available():
    points = _somas()
    uncapped = len(recruitment.field_recruitment(points, (470.0, 390.0, 950.0),
                                                 (470.0, 390.0, 500.0), -9600.0))
    capped = len(recruitment.field_recruitment(points, (470.0, 390.0, 950.0),
                                               (470.0, 390.0, 500.0), -9600.0,
                                               cap_um=50.0))
    assert capped < uncapped


def test_a_bad_input_is_refused():
    points = _somas()
    with pytest.raises(ValueError):
        recruitment.field_recruitment(np.zeros((0, 2)), (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), -1.0)
    with pytest.raises(ValueError):
        recruitment.field_recruitment(points, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), float("nan"))
    with pytest.raises(ValueError):
        recruitment.field_recruitment(points, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), -1.0,
                                      threshold_mv=0.0)


def test_the_cross_check_reports_both_datasets():
    points = _somas()
    report = recruitment.check_against_measurements(points)
    assert report["curve_max_error"] == 0
    assert report["site_map_max_error"] == 0
    assert len(report["curve"]) == len(recruitment.MEASURED_CURVE)
    assert len(report["site_map"]) == len(recruitment.MEASURED_SITE_MAP["counts"])
