"""Construct a bounded train of identical idealized stimulation pulses."""

from __future__ import annotations

import math


def pulse_train(*, start_ms, end_ms, rise_ms, interphase_gap_ms, shape,
                duration_ms, count=1, interval_ms=None):
    """Return piecewise-linear times and fractions, preserving step boundaries.

    Timing is a numerical input, not an assertion of electrode safety or physiology.
    """
    scalars = (start_ms, end_ms, rise_ms, interphase_gap_ms, duration_ms)
    if (any(isinstance(x, bool) or not isinstance(x, int | float) or not math.isfinite(x)
            for x in scalars) or type(count) is not int or not 1 <= count <= 1000
            or not 0 < start_ms < end_ms < duration_ms or rise_ms < 0
            or 2 * rise_ms > end_ms - start_ms or interphase_gap_ms < 0
            or shape not in ('monophasic', 'biphasic')
            or (shape == 'monophasic' and interphase_gap_ms != 0)):
        raise ValueError('Invalid pulse timing')
    width = end_ms - start_ms
    extent = width if shape == 'monophasic' else 2 * width + interphase_gap_ms
    if count == 1:
        if interval_ms is not None:
            raise ValueError('Interval is not used for a single pulse')
        interval = 0.
    else:
        if (isinstance(interval_ms, bool) or not isinstance(interval_ms, int | float)
                or not math.isfinite(interval_ms) or interval_ms <= extent):
            raise ValueError('Pulse interval must exceed pulse duration')
        interval = float(interval_ms)
    if start_ms + (count - 1) * interval + extent >= duration_ms:
        raise ValueError('Pulse train exceeds simulation duration')
    times, levels = [0.], [0.]
    for index in range(count):
        start = start_ms + index * interval
        end = start + width
        times.extend([start, start + rise_ms, end - rise_ms, end])
        levels.extend([0., 1., 1., 0.])
        if shape == 'biphasic':
            second_start = end + interphase_gap_ms
            second_end = second_start + width
            times.extend([second_start, second_start + rise_ms, second_end - rise_ms, second_end])
            levels.extend([0., -1., -1., 0.])
    times.append(duration_ms)
    levels.append(0.)
    return times, levels


def pulse_train_millisecond_means(**parameters):
    """Integrate the same pulse over 1 ms bins for the coarse network model.

    This preserves signed area, not sub-millisecond shape or peak amplitude.
    A short biphasic pulse may cancel inside a bin; that is a model limitation.
    """
    duration = parameters.get('duration_ms')
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or not float(duration).is_integer()
            or not 1 <= duration <= 1000):
        raise ValueError('Network duration must be an integer number of milliseconds')
    times, levels = pulse_train(**parameters)
    bins = [0.0] * int(duration)
    for left, right, first, last in zip(
        times[:-1], times[1:], levels[:-1], levels[1:], strict=True
    ):
        if right <= left:
            continue
        start = max(0, math.floor(left))
        stop = min(len(bins), math.ceil(right))
        slope = (last - first) / (right - left)
        for index in range(start, stop):
            lower, upper = max(left, index), min(right, index + 1)
            if upper > lower:
                low_value = first + slope * (lower - left)
                high_value = first + slope * (upper - left)
                bins[index] += (upper - lower) * (low_value + high_value) / 2
    return bins
