"""Summaries of model events, without an invented electrode recording."""

import numpy as np

_EVENT_CHECK_BLOCK = 1_000_000


def _verified_histogram(run, prefix, neurons, duration):
    try:
        times = np.asarray(run[f'{prefix}spike_times_ms'])
        indices = np.asarray(run[f'{prefix}spike_neurons'])
        counts = np.asarray(run[f'{prefix}counts'])
    except KeyError as exc:
        raise ValueError('Incomplete field-proxy event summary') from exc
    if (times.ndim != 1 or indices.shape != times.shape or indices.dtype.kind not in 'iu'
            or times.dtype.kind not in 'iuf' or counts.dtype.kind not in 'iuf'
            or counts.shape != (neurons,) or not np.isfinite(times).all()
            or not np.isfinite(counts).all() or np.any(counts != np.floor(counts))
            or np.any(times < 1) or np.any(times > duration)
            or np.any(times != np.floor(times)) or np.any(counts < 0)
            or np.any(counts > duration) or np.any(indices >= neurons)
            or (indices.dtype.kind == 'i' and np.any(indices < 0))):
        raise ValueError('Invalid field-proxy event summary')
    reconstructed = np.zeros(neurons, dtype=np.int64)
    tick_counts = np.zeros(duration + 1, dtype=np.int64)
    # Bound temporary allocations even for long, high-activity calculations.
    last_time, last_index = 0, -1
    for start in range(0, len(times), _EVENT_CHECK_BLOCK):
        end = min(start + _EVENT_CHECK_BLOCK, len(times))
        time_block, index_block = times[start:end], indices[start:end]
        if (time_block[0] < last_time
                or (time_block[0] == last_time and index_block[0] <= last_index)
                or np.any(time_block[1:] < time_block[:-1])
                or np.any((time_block[1:] == time_block[:-1])
                          & (index_block[1:] <= index_block[:-1]))):
            raise ValueError('Invalid field-proxy event order')
        reconstructed += np.bincount(index_block.astype(np.int64, copy=False), minlength=neurons)
        tick_counts += np.bincount(time_block.astype(np.int64, copy=False), minlength=duration + 1)
        last_time, last_index = time_block[-1], index_block[-1]
    if not np.array_equal(reconstructed, counts):
        raise ValueError('Invalid field-proxy event summary')
    return tick_counts.tolist(), int(np.count_nonzero(reconstructed)), len(times)


def field_proxy_preview(graph, run, waveform, provenance):
    per_tick, active, count = _verified_histogram(run, '', graph.size, len(waveform))
    control = None
    if any(name in run for name in (
        'control_spike_neurons', 'control_spike_times_ms', 'control_counts',
    )):
        control, _, _ = _verified_histogram(run, 'control_', graph.size, len(waveform))
    return {'kind': 'experimental-field-proxy', 'duration_ms': len(waveform),
            'time_step_ms': 1.0, 'neurons': graph.size,
            'spike_count': count, 'active_neurons': active,
            'spikes_by_ms': per_tick,
            'control_spikes_by_ms': control,
            'direct_field_exclusions': len(provenance['excluded_from_direct_field']),
            'contact_exclusions': len(provenance['excluded_contact_intersections']),
            'recording': None,
            'interpretation': 'uncalibrated model events; no extracellular recording'}
