"""Prepare exact midpoint samples of an explicitly piecewise-linear waveform.

Experimental input preparation only: solver timing and discontinuity semantics
must be checked against NEURON before this is used in the simulation service.
"""

import numpy as np


def midpoint_samples(times_ms, levels, *, dt_ms, steps):
    """Evaluate each time-step midpoint from original knots, not sampled endpoints.

    Repeated knot times represent a discontinuity; at the exact boundary the
    last value at that time is selected, matching numpy.interp. This convention
    is explicit and does not itself establish NEURON equivalence.
    """
    times = np.asarray(times_ms, dtype=np.float64)
    values = np.asarray(levels, dtype=np.float64)
    if (times.ndim != 1 or len(times) < 2 or values.shape != times.shape
            or not np.isfinite(times).all() or not np.isfinite(values).all()
            or np.any(np.diff(times) < 0) or isinstance(dt_ms, bool)
            or not isinstance(dt_ms, int | float) or not np.isfinite(dt_ms)
            or dt_ms <= 0 or type(steps) is not int or steps < 1):
        raise ValueError('Invalid piecewise-linear waveform or time grid')
    midpoints = (np.arange(steps, dtype=np.float64) + 0.5) * dt_ms
    if not np.isfinite(midpoints).all() or midpoints[0] < times[0] or midpoints[-1] > times[-1]:
        raise ValueError('Waveform does not cover the time grid')
    return np.interp(midpoints, times, values)


def kernel_midpoint_samples(times_ms, levels, *, dt_ms, steps):
    """Return the GPU kernel's indexed waveform, including unused index zero."""
    midpoints = midpoint_samples(times_ms, levels, dt_ms=dt_ms, steps=steps)
    result = np.empty(steps + 1, dtype=np.float64)
    result[0] = 0.0
    result[1:] = midpoints
    return result
