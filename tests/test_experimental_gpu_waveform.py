import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.waveform import (
    kernel_midpoint_samples,
    midpoint_samples,
)


def test_uses_original_knots_when_corner_is_inside_step():
    # Endpoints are both zero: their average would miss this narrow pulse.
    values = midpoint_samples([0, .25, .5, .75, 1], [0, 0, 1, 0, 0], dt_ms=1., steps=1)
    np.testing.assert_array_equal(values, [1.])


def test_discontinuity_uses_last_knot_at_exact_midpoint():
    values = midpoint_samples([0, .5, .5, 1], [0, 0, 1, 1], dt_ms=1., steps=1)
    np.testing.assert_array_equal(values, [1.])


def test_kernel_samples_include_unused_initial_index_and_preserve_step():
    values = kernel_midpoint_samples([0, 1, 1, 2], [0, 0, 1, 1], dt_ms=.5, steps=4)
    np.testing.assert_array_equal(values, [0, 0, 0, 1, 1])


def test_kernel_samples_reject_uncovered_grid():
    with pytest.raises(ValueError):
        kernel_midpoint_samples([0, 1], [0, 1], dt_ms=1, steps=2)


@pytest.mark.parametrize('times,levels,dt,steps', [
    ([0, 1], [0, 1], 1, 2), ([0, 1, .5], [0, 1, 0], .1, 1),
    ([0, 1], [0, float('nan')], .1, 1), ([0, 1], [0, 1], True, 1),
])
def test_rejects_invalid_or_uncovered_inputs(times, levels, dt, steps):
    with pytest.raises(ValueError):
        midpoint_samples(times, levels, dt_ms=dt, steps=steps)
