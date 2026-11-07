import numpy as np
import pytest

from service.domain.pulse_train import pulse_train, pulse_train_millisecond_means


def test_network_bins_preserve_narrow_pulse_area_and_phase_cancellation():
    settings = dict(start_ms=2.1, end_ms=2.3, rise_ms=0., interphase_gap_ms=0.,
                    shape='monophasic', duration_ms=10.)
    means = pulse_train_millisecond_means(**settings)
    assert len(means) == 10
    assert means[2] == pytest.approx(.2)
    assert sum(means) == pytest.approx(.2)
    biphasic = pulse_train_millisecond_means(**{**settings, 'shape': 'biphasic'})
    assert sum(biphasic) == pytest.approx(0., abs=1e-12)
    assert biphasic[2] == pytest.approx(0., abs=1e-12)


def test_network_bins_preserve_ramped_pulse_across_boundaries():
    values = pulse_train_millisecond_means(start_ms=1.5, end_ms=3.5, rise_ms=.5,
        interphase_gap_ms=0., shape='monophasic', duration_ms=5.)
    assert values == pytest.approx([0., .25, 1., .25, 0.])
    with pytest.raises(ValueError, match='integer'):
        pulse_train_millisecond_means(start_ms=1., end_ms=2., rise_ms=0.,
            interphase_gap_ms=0., shape='monophasic', duration_ms=5.5)


def test_single_pulse_preserves_existing_piecewise_waveform():
    times, levels = pulse_train(start_ms=2., end_ms=3., rise_ms=.2, interphase_gap_ms=0.,
                                shape='monophasic', duration_ms=10.)
    np.testing.assert_array_equal(times, [0, 2, 2.2, 2.8, 3, 10])
    np.testing.assert_array_equal(levels, [0, 0, 1, 1, 0, 0])


def test_two_pulses_and_charge_balanced_biphasic_train():
    times, levels = pulse_train(start_ms=2., end_ms=3., rise_ms=.2, interphase_gap_ms=.5,
                                shape='biphasic', duration_ms=15., count=2, interval_ms=5.)
    assert times == sorted(times)
    np.testing.assert_allclose(np.trapezoid(levels, times), 0, atol=1e-12)
    np.testing.assert_allclose(np.interp([2.5, 4, 7.5, 9], times, levels), [1, -1, 1, -1])


@pytest.mark.parametrize('overrides', [
    {'count': 0}, {'count': True}, {'count': 2, 'interval_ms': 1},
    {'count': 2, 'interval_ms': float('nan')}, {'count': 3, 'interval_ms': 5},
    {'count': 1, 'interval_ms': 5}, {'interphase_gap_ms': 1}, {'rise_ms': .6},
])
def test_invalid_train_is_rejected(overrides):
    settings = dict(start_ms=2., end_ms=3., rise_ms=.2, interphase_gap_ms=0.,
                    shape='monophasic', duration_ms=10.)
    with pytest.raises(ValueError):
        pulse_train(**{**settings, **overrides})
