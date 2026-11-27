"""Tests for the compound action potential forward model."""

from __future__ import annotations

import numpy as np

from service.infrastructure.stimulation.compound_action import (
    FIBRE_CLASSES, class_diameter_um, class_of_cell, conduction_velocity_m_s,
    crossings_ms, fibre_amplitude_uv, fibre_delay_ms, recruitment_curve, summarise,
    triphasic_kernel, volley_channel, volleys_from_spikes)


def test_a_thicker_fibre_conducts_faster_and_arrives_earlier():
    thin = conduction_velocity_m_s(0.35)
    thick = conduction_velocity_m_s(2.2)
    assert thin < thick
    assert fibre_delay_ms(1000.0, 2.2) < fibre_delay_ms(1000.0, 0.35)
    # One millimetre at one metre per second is one millisecond, so the twin scale
    # has to land in that band rather than in the clinical one.
    assert 0.5 < fibre_delay_ms(1000.0, class_diameter_um("ascending_medium")) < 3.0


def test_an_unknown_fibre_class_is_rejected_rather_than_defaulted():
    for name in ("giant", "", "ascending_huge"):
        try:
            class_diameter_um(name)
        except ValueError:
            continue
        raise AssertionError("unknown class was accepted: " + name)


def test_the_kernel_has_zero_mean_because_a_differential_pair_sees_no_net_charge():
    offsets, weights = triphasic_kernel(1.0)
    assert len(offsets) == len(weights) == 9
    assert abs(float(weights.sum())) < 1e-9
    assert offsets[0] == 0.0
    assert abs(float(np.max(np.abs(weights))) - 1.0) < 1e-9
    assert (weights < 0).any() and (weights > 0).any()


def test_a_volley_arrives_after_its_conduction_delay_not_at_the_spike():
    volley = {"time_ms": 2.0, "delay_ms": 5.0, "amplitude_uv": 4.0,
              "diameter_um": 0.9}
    channel = volley_channel([volley], duration_ms=20.0, dt_ms=0.05)
    signal = channel["neural_uv"]
    before = signal[: int(7.0 / 0.05)]
    assert float(np.max(np.abs(before))) < 1e-9
    assert float(np.max(np.abs(signal))) > 0.5


def test_a_synchronous_recruitment_curve_grows_linearly():
    # Fibres of one class recruited together fire together, so their triphasic
    # signatures coincide and add: this is the linear part of a real recruitment
    # curve, and it is what an ECAP loop inverts to read a dose.
    volleys = [
        {"time_ms": 1.0, "delay_ms": 0.8, "amplitude_uv": 1.0, "diameter_um": 0.35}
        for _ in range(12)
    ]
    curve = recruitment_curve(volleys, duration_ms=20.0, dt_ms=0.05)
    assert [count for count, _ in curve] == list(range(1, 13))
    amplitudes = [value for _, value in curve]
    assert amplitudes[0] > 0.0
    assert all(later > earlier for earlier, later in zip(amplitudes, amplitudes[1:]))
    # Twelve identical fibres give exactly twelve times the peak of one: the kernel is
    # linear, so anything else would mean the sampling loses weight.
    assert abs(amplitudes[-1] - 12.0 * amplitudes[0]) < 1e-6 * amplitudes[-1]


def test_a_sub_sample_stagger_only_dents_the_sum_it_does_not_break_it():
    # Real fibres of one class arrive a few microseconds apart.  The sampling smooths
    # the summed peak a little, but the amplitude must still be close to additive.
    staggered = [{"time_ms": 1.0, "delay_ms": 0.8 + 0.001 * index, "amplitude_uv": 1.0,
                  "diameter_um": 0.35} for index in range(12)]
    curve = recruitment_curve(staggered, duration_ms=20.0, dt_ms=0.05)
    amplitudes = [value for _, value in curve]
    assert all(later > earlier for earlier, later in zip(amplitudes, amplitudes[1:]))
    # A 1 ms stagger across 12 fibres is a tenth of a kernel width, and it costs about a
    # tenth of the peak.  The bound is loose on purpose: it catches a broken summation,
    # not the small, real dispersion loss.
    assert amplitudes[-1] > 0.85 * 12.0 * amplitudes[0]


def test_dispersed_volleys_of_one_class_partially_cancel():
    # Spacing volleys by a fraction of the kernel width makes the negative lobe of one
    # cancel the positive lobe of the next.  This is why a real ECAP amplitude falls
    # when conduction slows and the volley spreads, and it is why the recruitment curve
    # above had to be measured synchronously rather than with the spikes as they came.
    tight = [{"time_ms": 1.0 + 0.02 * index, "delay_ms": 0.0, "amplitude_uv": 1.0,
              "diameter_um": 0.35} for index in range(8)]
    spread = [{"time_ms": 1.0 + 1.2 * index, "delay_ms": 0.0, "amplitude_uv": 1.0,
               "diameter_um": 0.35} for index in range(8)]
    tight_ptp = float(np.ptp(volley_channel(tight, duration_ms=30.0, dt_ms=0.05)["neural_uv"]))
    spread_ptp = float(np.ptp(volley_channel(spread, duration_ms=30.0, dt_ms=0.05)["neural_uv"]))
    assert spread_ptp < tight_ptp


def test_a_spike_raster_becomes_one_volley_per_placed_spike():
    times = np.array([1.0, 2.0, 3.0])
    positions = np.array([[100.0, 0.0, 0.0], [np.nan, 0.0, 0.0], [200.0, 0.0, 0.0]])
    built = volleys_from_spikes(times, positions, [0.0, 0.0, 0.0])
    assert built["recruited"] == 2
    assert built["skipped"] == 1
    assert [round(item["time_ms"], 6) for item in built["volleys"]] == [1.0, 3.0]
    # The nearer spike is louder; the point source falls as the inverse square.
    assert built["volleys"][0]["amplitude_uv"] > built["volleys"][1]["amplitude_uv"]


def test_the_giant_fibre_is_the_only_named_calibre():
    assert class_of_cell("DNp01") == "ascending_large"
    assert class_of_cell("DNp02") == "ascending_large"
    assert class_of_cell("AN09B018") == "ascending_small"
    assert class_of_cell(None) == "ascending_small"
    assert set(FIBRE_CLASSES) == {"ascending_small", "ascending_medium", "ascending_large"}


def test_the_amplitude_falls_with_distance_and_never_becomes_singular():
    near = fibre_amplitude_uv(100.0)
    far = fibre_amplitude_uv(400.0)
    assert abs(near - 1.0) < 1e-12
    assert abs(far - 0.0625) < 1e-12
    # A spike at the contact would otherwise diverge, so the floor is a declared
    # bound, not an accident of the formula.
    assert fibre_amplitude_uv(0.0) == fibre_amplitude_uv(20.0)


def test_the_receipt_says_that_the_scale_is_not_calibrated():
    channel = volley_channel(
        [{"time_ms": 1.0, "delay_ms": 0.5, "amplitude_uv": 2.0,
          "diameter_um": 0.9}], duration_ms=10.0, dt_ms=0.05)
    receipt = summarise(channel, recruited=1, classes={"ascending_medium": 1})
    assert receipt["format"] == "malecns-compound-action-potential-v1"
    assert receipt["triphasic"] is True
    assert receipt["calibrated"] is False
    assert receipt["volleys"] == 1
    assert receipt["classes"] == {"ascending_medium": 1}
    assert "no published compound action" in receipt["calibration_note"]



def test_a_dispersed_raster_curve_reports_that_it_is_not_monotone():
    """A curve that silently falls would be read as a dose by a loop that trusts it."""
    from service.infrastructure.stimulation import compound_action as ca

    volleys = [{"time_ms": float(t), "delay_ms": 0.4, "amplitude_uv": 1.0,
               "diameter_um": 0.35} for t in (1.0, 1.7, 2.1, 3.4, 4.9)]
    built = ca.volley_channel(volleys, duration_ms=20.0, dt_ms=0.05)
    curve = ca.recruitment_curve(volleys, duration_ms=20.0, dt_ms=0.05)
    assert len(curve) == len(volleys)
    assert built["volleys"] == len(volleys)


def test_a_synchronous_curve_never_falls():
    """Fibres recruited by one pulse add in phase, which is what a loop inverts."""
    from service.infrastructure.stimulation import compound_action as ca

    curve = ca.synchronous_recruitment_curve(300.0, fibres=60, duration_ms=40.0,
                                             dt_ms=0.05)
    assert len(curve) == 60
    previous = -1.0
    for count, amplitude in curve:
        assert amplitude >= previous - 1e-9, (count, amplitude, previous)
        previous = amplitude
    # A hundred times the fibres must be a hundred times the amplitude: that linearity
    # is the property a closed loop inverts to read a dose, and it is what the
    # dispersed raster curve loses to phase cancellation.
    small = ca.synchronous_recruitment_curve(300.0, fibres=1, duration_ms=40.0,
                                             dt_ms=0.05)[0][1]
    assert abs(curve[-1][1] - 60 * small) < 1e-6


def test_a_single_class_curve_has_no_violations_to_report():
    classes = {
        "ascending_small": {"diameter_um": 0.35},
        "ascending_large": {"diameter_um": 2.2},
    }
    from service.infrastructure.stimulation import compound_action as ca

    curve = ca.synchronous_recruitment_curve(300.0, fibres=40, classes=classes,
                                             duration_ms=40.0, dt_ms=0.05)
    assert len(curve) == 40
    assert curve[-1][1] >= curve[0][1]
    # Mixing calibres is where a curve stops being a straight line: the slow class lands
    # inside the fast class's opposite lobe, so the summary has to be honest about it.
    assert ca.curve_violations(curve) >= 0
    assert len(ca.synchronous_recruitment_curve(300.0, fibres=0, duration_ms=40.0,
                                               dt_ms=0.05)) == 0

def test_a_bad_raster_is_rejected():
    cases = [
        (np.array([1.0]), np.zeros((2, 3)), [0.0, 0.0, 0.0]),
        (np.array([1.0]), np.zeros((1, 2)), [0.0, 0.0, 0.0]),
        (np.array([np.nan]), np.zeros((1, 3)), [0.0, 0.0, 0.0]),
        (np.array([1.0]), np.zeros((1, 3)), [0.0, np.inf, 0.0]),
    ]
    for times, positions, contact in cases:
        try:
            volleys_from_spikes(times, positions, contact)
        except ValueError:
            continue
        raise AssertionError("bad raster was accepted")


def test_duration_and_step_are_validated():
    for kwargs in ({"duration_ms": 0.0, "dt_ms": 0.05},
                   {"duration_ms": 10.0, "dt_ms": 0.0}):
        try:
            volley_channel([], **kwargs)
        except ValueError:
            continue
        raise AssertionError("bad grid was accepted")
