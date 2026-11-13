"""Bind an experimental GPU trace to a reproducible stimulation waveform."""

import numpy as np

from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.point_field import bipolar_potential_mv
from service.infrastructure.stimulation.swc_reference import _event_digest
from service.infrastructure.stimulation.virtual_current import junction_currents

from .waveform import kernel_midpoint_samples


def attach_stimulation(arrays, *, config, events, stimulus_midpoint, field_current_na, junctions):
    """Return recording-compatible arrays after checking field and waveform.

    Geometry and configuration provenance must still be verified by the caller.
    The function does not claim biological validity or publish an experiment.
    """
    if not isinstance(arrays, dict) or not isinstance(config, dict) or not isinstance(events, list):
        raise ValueError('Invalid recording inputs')
    time = np.asarray(arrays['time_ms'], dtype=float)
    dt_ms = config.get('dt_ms', .025)
    if type(dt_ms) not in (int, float) or dt_ms not in (.025, .05):
        raise ValueError('Unsupported GPU time step')
    if (time.ndim != 1 or len(time) < 2 or not np.isfinite(time).all()
            or not np.allclose(time, np.arange(len(time)) * dt_ms, rtol=0, atol=1e-10)):
        raise ValueError('GPU recording time grid does not match configuration')
    start, end = config['pulse_start_ms'], config['pulse_end_ms']
    rise, gap = config['rise_time_ms'], config['interphase_gap_ms']
    shape = config['pulse_shape']
    count, interval = config.get('pulse_count', 1), config.get('pulse_interval_ms')
    times, levels = pulse_train(start_ms=start, end_ms=end, rise_ms=rise,
                                interphase_gap_ms=gap, shape=shape,
                                duration_ms=float(time[-1]), count=count, interval_ms=interval)
    expected = kernel_midpoint_samples(times, levels, dt_ms=dt_ms, steps=len(time) - 1)
    actual = np.asarray(stimulus_midpoint, dtype=float)
    if actual.shape != expected.shape or not np.array_equal(actual, expected):
        raise ValueError('GPU stimulus does not match recording configuration')
    source, return_contact = config['source_um'], config['return_um']
    current, conductivity, clearance = (config['current_na'], config['conductivity_s_m'],
                                        config['clearance_um'])
    field = bipolar_potential_mv(arrays['midpoints_um'], source, return_contact, current,
                                 conductivity, clearance_um=clearance)
    field_current = np.asarray(field_current_na, dtype=float)
    if field_current.shape != field.shape or not np.allclose(
            field_current, junction_currents(field, junctions), rtol=1e-12, atol=1e-14):
        raise ValueError('GPU field does not match recording configuration')
    parameters = [*source, *return_contact, current, conductivity, clearance, start, end, rise, gap,
                  1 if shape == 'biphasic' else 0]
    if count > 1:
        parameters.extend([count, interval])
    return {**arrays, 'field_mv': field,
            'stimulation_parameters': np.asarray(parameters, dtype=float),
            'stimulus_fraction': np.interp(time, times, levels),
            'synaptic_events_sha256': _event_digest(events)}


def attach_windowed_artifact(replay, cells, *, config, stimulus_midpoint,
                             electrode_um, reference_um):
    """Add one direct resistive artifact after checking every prepared source.

    This does not validate source archive identity or create full-cell traces.
    The caller must verify those independently and retain all provenance.
    """
    if (not isinstance(replay, dict) or not isinstance(cells, list) or not cells
            or not isinstance(config, dict) or not isinstance(replay.get('sources'), dict)
            or any(not isinstance(cell, dict) or type(cell.get('id')) is not int for cell in cells)
            or list(replay['sources']) != [cell['id'] for cell in cells]
            or len({cell['id'] for cell in cells}) != len(cells)):
        raise ValueError('Invalid windowed artifact inputs')
    time = np.asarray(replay.get('time_ms'), dtype=float)
    neural = np.asarray(replay.get('neural_uv'), dtype=float)
    if time.ndim != 1 or neural.shape != time.shape or not np.isfinite(neural).all():
        raise ValueError('Invalid windowed recording')
    fraction = None
    for cell in cells:
        checked = attach_stimulation(
            {'time_ms': time, 'midpoints_um': cell['geometry']['midpoints_um']},
            config=config, events=cell['events'], stimulus_midpoint=stimulus_midpoint,
            field_current_na=cell['field_current_na'], junctions=cell['geometry']['junctions'])
        if fraction is None:
            fraction = checked['stimulus_fraction']
        elif not np.array_equal(fraction, checked['stimulus_fraction']):
            raise ValueError('Inconsistent windowed stimulus')
    potential = bipolar_potential_mv([electrode_um, reference_um], config['source_um'],
        config['return_um'], config['current_na'], config['conductivity_s_m'],
        clearance_um=config['clearance_um'])
    artifact = (potential[0] - potential[1]) * 1000 * fraction
    total = neural + artifact
    if not np.isfinite(artifact).all() or not np.isfinite(total).all():
        raise ValueError('Non-finite windowed recording')
    return {**replay, 'stimulus_fraction': fraction, 'stimulus_artifact_uv': artifact,
            'total_uv': total}
