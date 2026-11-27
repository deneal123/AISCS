"""Behavioural detection is only worth a number if it cannot read the label."""

import pytest

from service.infrastructure.body import behavioural_detection as detection


def _record(site, current, curl, displacement, latency, motor=0, spike=100):
    body = {"displacement_mm": displacement, "displacement_x_mm": displacement,
            "displacement_z_mm": 0.0, "curl_change_rad": curl,
            "peak_height_cm": 0.05, "min_height_cm": 0.045,
            "motor_spikes": motor, "mapped_first_tick_ms": latency,
            "escape_latency_ms": latency}
    return {"site_um": list(site), "current_na": current, "duration_ms": 120,
            "body": body, "network": {"spike_count": spike},
            "source_cell_count": 10}


def _corpus():
    """Three sites, high currents curl and move, low ones do not."""
    records = []
    for index, site in enumerate(((470., 390., 850.), (470., 390., 950.),
                                 (470., 390., 1000.))):
        for current in (-9600., -4800., -3600., -1200., 0.):
            noxious = current <= detection.NOXIOUS_CURRENT_NA
            records.append(_record(
                site, current,
                curl=-0.17 if noxious else -0.012,
                displacement=6.0 + index if noxious else 1.0 + 0.1 * index,
                latency=10.0 if noxious else None,
                motor=400 if noxious else 5))
    return records


def test_a_forbidden_feature_is_refused_before_any_number_is_produced():
    for name in ("current_na", "spike_count", "source_cell_count",
                 "escape_latency_ms", "recruited_afferents", "site_um"):
        with pytest.raises(ValueError):
            detection.assert_no_leakage(("displacement_mm", name))


def test_no_feature_reads_anything_outside_the_body_block():
    records = _corpus()
    features = detection.behaviour_features(records[0])
    assert "current_na" not in features
    assert "spike_count" not in features
    # The escape latency is a body measurement, but it IS the escape label, so a
    # detector aimed at the escape may not read it either.
    assert "escape_latency_ms" not in features


def test_a_missing_latency_is_zero_plus_a_flag_not_a_sentinel():
    quiet = _record((0., 0., 0.), -100., curl=-0.01, displacement=1.0, latency=None)
    heard = _record((0., 0., 0.), -9600., curl=-0.17, displacement=6.0, latency=10.0)
    assert detection.behaviour_features(quiet)["mapped_first_tick_ms"] == 0.0
    assert detection.behaviour_features(quiet)["motor_heard"] == 0.0
    assert detection.behaviour_features(heard)["motor_heard"] == 1.0
    assert detection.behaviour_features(heard)["mapped_first_tick_ms"] == 10.0


def test_the_label_is_the_applied_current_not_the_body():
    noxious = _record((0., 0., 0.), -3600., curl=-0.01, displacement=0.0, latency=None)
    mild = _record((0., 0., 0.), -1200., curl=-0.17, displacement=9.0, latency=10.0)
    assert detection.is_noxious(noxious) is True
    assert detection.is_noxious(mild) is False


def test_detection_is_grouped_by_site_and_beats_its_permutation_control():
    result = detection.detect(_corpus())
    assert result["sites"] == 3
    # Three noxious currents (-9600, -4800, -3600) at three sites: nine positives.
    assert result["positives"] == 9, result["positives"]
    assert result["pooled_auc"] > 0.9, result["pooled_auc"]
    assert result["permutation_auc_mean"] is None or result["permutation_auc_mean"] < 0.9


def test_one_site_cannot_be_held_out_of_one_site():
    records = [_record((1., 1., 1.), -9600., curl=-0.17, displacement=6.0, latency=10.0),
               _record((1., 1., 1.), 0., curl=-0.01, displacement=1.0, latency=None)]
    with pytest.raises(ValueError):
        detection.detect(records)


def test_the_result_says_it_is_not_a_feeling():
    result = detection.detect(_corpus())
    assert "not a claim about a feeling" in result["not_a_feeling"].lower()
    assert "body block only" in result["leakage_rule"]
    line = detection.summary(result)
    assert line["episodes"] == 15 and line["sites"] == 3

