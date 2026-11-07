"""Summaries of model events, without an invented electrode recording."""

import numpy as np


def field_proxy_preview(graph, run, waveform, provenance):
    times = np.asarray(run['spike_times_ms'])
    counts = np.asarray(run['counts'])
    if (times.ndim != 1 or counts.shape != (graph.size,) or not np.isfinite(times).all()
            or not np.isfinite(counts).all() or np.any(counts != np.floor(counts))
            or np.any(times < 1) or np.any(times > len(waveform))
            or np.any(times != np.floor(times)) or np.any(counts < 0)
            or int(counts.sum()) != len(times)):
        raise ValueError('Invalid field-proxy event summary')
    per_tick = np.bincount(times.astype(np.int64), minlength=len(waveform) + 1)
    control = None
    if 'control_spike_times_ms' in run:
        control_times = np.asarray(run['control_spike_times_ms'])
        if (control_times.ndim != 1 or not np.isfinite(control_times).all()
                or np.any(control_times < 1) or np.any(control_times > len(waveform))
                or np.any(control_times != np.floor(control_times))):
            raise ValueError('Invalid control event summary')
        control = np.bincount(control_times.astype(np.int64), minlength=len(waveform) + 1).tolist()
    return {'kind': 'experimental-field-proxy', 'duration_ms': len(waveform),
            'time_step_ms': 1.0, 'neurons': graph.size,
            'spike_count': int(len(times)), 'active_neurons': int(np.count_nonzero(counts)),
            'spikes_by_ms': per_tick.tolist(),
            'control_spikes_by_ms': control,
            'direct_field_exclusions': len(provenance['excluded_from_direct_field']),
            'contact_exclusions': len(provenance['excluded_contact_intersections']),
            'recording': None,
            'interpretation': 'uncalibrated model events; no extracellular recording'}
