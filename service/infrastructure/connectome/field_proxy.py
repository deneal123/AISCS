"""Explicit experimental coupling of a field descriptor to the LIF network.

The descriptor and gain are inputs, not a biophysical recruitment prediction.
"""

from __future__ import annotations

import numpy as np

from service.domain.target_response_limits import MAX_TARGET_RESPONSE_VALUES, network_sample_ticks
from service.infrastructure.connectome.kernel import advance, signed_weights


def descriptor_from_rows(ids, rows, *, allow_partial_geometry=False):
    """Convert ordered, previously verified field rows without filling gaps.

    Source integrity and provenance must be verified by the caller. A missing
    curvature is unknown, not evidence of zero coupling.
    """
    if type(allow_partial_geometry) is not bool:
        raise ValueError('Invalid partial geometry policy')
    values = np.empty(len(ids), dtype=np.float64)
    count = 0
    for count, row in enumerate(rows, start=1):
        if count > len(ids) or not isinstance(row, dict):
            raise ValueError('Invalid field row count')
        value = row.get('max_abs_curvature_signed_mv_per_um2')
        allowed = {'ok', 'partial_geometry'} if allow_partial_geometry else {'ok'}
        if (row.get('body_id') != str(ids[count - 1]) or row.get('status') not in allowed
                or type(value) not in (int, float) or not np.isfinite(value)):
            raise ValueError('Missing, partial, or mismatched field descriptor')
        values[count - 1] = value
    if count != len(ids):
        raise ValueError('Incomplete field descriptors')
    return values


def run_field_proxy(graph, *, descriptor, waveform, gain, seed, capture_sparse_delta=False):
    """Propagate a signed per-cell descriptor with an explicit empirical gain.

    ``descriptor`` is in mV/um² for the declared reference current and
    ``waveform`` scales that current at each 1 ms tick. ``gain`` maps the
    descriptor to the kernel's mV drive proxy; it must be supplied by the
    caller and has not been calibrated here. Missing cells must not be filled
    with invented values: incomplete/nonfinite descriptors are rejected.
    """
    desc = np.asarray(descriptor, dtype=np.float64)
    wave = np.asarray(waveform, dtype=np.float64)
    if (desc.shape != (graph.size,) or wave.ndim != 1 or not 1 <= wave.size <= 1000
            or not np.isfinite(desc).all() or not np.isfinite(wave).all()
            or isinstance(gain, bool) or not isinstance(gain, int | float)
            or not np.isfinite(gain) or type(seed) is not int or not 0 <= seed <= 2**31 - 1
            or type(capture_sparse_delta) is not bool):
        raise ValueError('Invalid or incomplete experimental field input')
    drive_reference = desc * float(gain)
    if not np.isfinite(drive_reference).all():
        raise ValueError('Non-finite field drive')
    voltage = np.random.default_rng(seed).uniform(0, 2, graph.size).astype(np.float32)
    current = np.zeros(graph.size, np.float32)
    refractory = np.zeros(graph.size, np.int16)
    queue = np.zeros((3, graph.size), np.float32)
    weights = signed_weights(graph.ptr, graph.counts, graph.signs, .075)
    spike_neurons, spike_times = [], []
    counts = np.zeros(graph.size, np.int32)
    if capture_sparse_delta:
        ticks = network_sample_ticks(graph.size, len(wave))
        if ticks is None or np.asarray(graph.ids).shape != (graph.size,):
            raise ValueError('Cannot capture bounded whole-network snapshots')
        sampled_active = np.empty((len(ticks), graph.size), np.float32)
        sampled_control = np.empty_like(sampled_active)
        sampled_active[0] = sampled_control[0] = voltage
        next_sample = 1
        control_voltage = voltage.copy()
        control_current = np.zeros(graph.size, np.float32)
        control_refractory = np.zeros(graph.size, np.int16)
        control_queue = np.zeros((3, graph.size), np.float32)
        control_spike_neurons, control_spike_times = [], []
        control_counts = np.zeros(graph.size, np.int32)
        no_drive = np.zeros(graph.size, np.float32)
        offsets, indices, values = [0, 0], [], []
        total_values, overflow = 0, False
    for clock, scale in enumerate(wave):
        with np.errstate(over='ignore', invalid='ignore'):
            drive = (drive_reference * scale).astype(np.float32)
        if not np.isfinite(drive).all():
            raise ValueError('Non-finite field drive')
        fired = advance(graph.ptr, graph.posts, weights, voltage, current,
                        refractory, queue, clock, drive, 1)
        if capture_sparse_delta:
            control_fired = advance(graph.ptr, graph.posts, weights, control_voltage,
                                    control_current, control_refractory, control_queue,
                                    clock, no_drive, 1)
            control_active = np.flatnonzero(control_fired).astype(np.int32)
            if control_active.size:
                control_spike_neurons.append(control_active)
                control_spike_times.append(np.full(control_active.size, clock + 1, np.float32))
            control_counts += control_fired
            if not np.isfinite(control_voltage).all() or not np.isfinite(control_current).all():
                raise ValueError('Non-finite control state')
            if next_sample < len(ticks) and clock + 1 == ticks[next_sample]:
                sampled_active[next_sample] = voltage
                sampled_control[next_sample] = control_voltage
                next_sample += 1
            if not overflow:
                delta = voltage - control_voltage
                changed = np.flatnonzero(delta).astype(np.int32)
                total_values += len(changed)
                if total_values > MAX_TARGET_RESPONSE_VALUES:
                    overflow = True
                    offsets, indices, values = [], [], []
                else:
                    indices.append(changed)
                    values.append(delta[changed])
                    offsets.append(total_values)
        active = np.flatnonzero(fired).astype(np.int32)
        if active.size:
            spike_neurons.append(active)
            spike_times.append(np.full(active.size, clock + 1, np.float32))
        counts += fired
        if not np.isfinite(voltage).all() or not np.isfinite(current).all():
            raise ValueError('Non-finite network state')
    result = {'spike_neurons': np.concatenate(spike_neurons) if spike_neurons
            else np.empty(0, np.int32),
            'spike_times_ms': np.concatenate(spike_times) if spike_times
            else np.empty(0, np.float32), 'counts': counts,
            'final_voltage_relative_mv': voltage, 'final_synaptic_drive_mv': current,
            'interpretation': 'uncalibrated field-curvature-to-LIF drive; '
                              'not biological recruitment'}
    if capture_sparse_delta:
        result['control_spike_neurons'] = (np.concatenate(control_spike_neurons)
                                          if control_spike_neurons else np.empty(0, np.int32))
        result['control_spike_times_ms'] = (np.concatenate(control_spike_times)
                                          if control_spike_times else np.empty(0, np.float32))
        result['control_counts'] = control_counts
        result['target_response'] = {'target_ids': np.asarray(graph.ids),
            'time_ms': np.asarray(ticks, np.float32), 'active_relative_mv': sampled_active,
            'control_relative_mv': sampled_control}
        result['sparse_delta'] = ({'status': 'limit_exceeded'} if overflow else {
            'status': 'recorded', 'offsets': np.asarray(offsets, dtype=np.uint32),
            'indices': np.concatenate(indices) if indices else np.empty(0, np.int32),
            'values': np.concatenate(values) if values else np.empty(0, np.float32)})
    return result
