"""Check the one-millisecond stimulus projection at the service boundary."""

import math


def _number(value):
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError('Invalid pulse parameter')
    return float(value)


def validate_projected_waveform(simulation, waveform):
    """Verify signed bin averages independently of the generator's projection.

    This checks input consistency only; it does not validate biological response.
    """
    duration = _number(simulation['duration_ms'])
    start = _number(simulation['pulse_start_ms'])
    end = _number(simulation['pulse_end_ms'])
    rise = _number(simulation['rise_time_ms'])
    gap = _number(simulation['interphase_gap_ms'])
    shape = simulation['pulse_shape']
    count = simulation.get('pulse_count')
    interval = simulation.get('pulse_interval_ms')
    if (duration != int(duration) or not 1 <= duration <= 1000 or
            not 0 < start < end < duration or rise < 0 or 2 * rise > end - start or
            gap < 0 or shape not in ('monophasic', 'biphasic') or
            (shape == 'monophasic' and gap != 0)):
        raise ValueError('Invalid pulse timing')
    width = end - start
    extent = width if shape == 'monophasic' else 2 * width + gap
    if count is None:
        if interval is not None:
            raise ValueError('Unexpected pulse interval')
        count, interval = 1, 0.
    else:
        if type(count) is not int or not 2 <= count <= 1000:
            raise ValueError('Invalid pulse count')
        interval = _number(interval)
        if interval <= extent:
            raise ValueError('Overlapping pulses')
    if start + (count - 1) * interval + extent >= duration:
        raise ValueError('Pulse exceeds simulation')
    if not isinstance(waveform, list) or len(waveform) != int(duration):
        raise ValueError('Invalid projected waveform')
    expected = [0.] * int(duration)

    def add_phase(phase_start, sign):
        phase_end = phase_start + width
        # Integrate the rising, constant and falling pieces in each touched bin.
        for index in range(int(phase_start), min(int(duration), math.ceil(phase_end))):
            lo, hi = max(index, phase_start), min(index + 1., phase_end)
            if hi <= lo:
                continue
            left, right = max(lo, phase_start + rise), min(hi, phase_end - rise)
            area = max(0., right - left)
            if rise:
                a, b = lo, min(hi, phase_start + rise)
                if b > a:
                    area += ((b - phase_start) ** 2 - (a - phase_start) ** 2) / (2 * rise)
                a, b = max(lo, phase_end - rise), hi
                if b > a:
                    area += ((phase_end - a) ** 2 - (phase_end - b) ** 2) / (2 * rise)
            expected[index] += sign * area

    for pulse in range(count):
        phase_start = start + pulse * interval
        add_phase(phase_start, 1.)
        if shape == 'biphasic':
            add_phase(phase_start + width + gap, -1.)
    for actual, target in zip(waveform, expected, strict=True):
        if not math.isclose(_number(actual), target, rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError('Projected waveform differs from requested pulse')
