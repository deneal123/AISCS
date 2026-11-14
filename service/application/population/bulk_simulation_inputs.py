"""Translate the existing experiment settings to independent GPU inputs."""

import numpy as np

from service.domain.contracts.replay import ReplaySimulation
from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.experimental_gpu.fast_cable import Params
from service.infrastructure.stimulation.experimental_gpu.waveform import kernel_midpoint_samples


def bulk_simulation_inputs(simulation):
    """Build one time grid and stimulus; this does not add network coupling."""
    config = ReplaySimulation.model_validate(simulation)
    if config.source_model != 'pointsource' or config.dt_ms not in (.025, .05):
        raise ValueError('Independent GPU recording requires point sources and supported time step')
    if not config.allow_disconnected:
        raise ValueError('Independent GPU recording requires disconnected morphology support')
    steps = round(config.duration_ms / config.dt_ms)
    if steps > 40000:
        raise ValueError('Independent GPU recording exceeds the 40000-step limit')
    times, levels = pulse_train(start_ms=config.pulse_start_ms, end_ms=config.pulse_end_ms,
        rise_ms=config.rise_time_ms, interphase_gap_ms=config.interphase_gap_ms,
        shape=config.pulse_shape, duration_ms=config.duration_ms,
        count=config.pulse_count or 1, interval_ms=config.pulse_interval_ms)
    stimulus = kernel_midpoint_samples(times, levels, dt_ms=config.dt_ms, steps=steps)
    params = Params(source_um=config.source_um, return_um=config.return_um,
        current_na=config.current_na, conductivity_s_m=config.conductivity_s_m,
        clearance_um=config.clearance_um, nseg=config.nseg_per_edge)
    params.checked()
    return {'params': params, 'stimulus': stimulus,
            'time_ms': np.arange(steps + 1, dtype=float) * config.dt_ms,
            'dt_ms': config.dt_ms, 'electrode_um': list(config.electrode_um),
            'reference_um': list(config.reference_um),
            'conductivity_s_m': config.conductivity_s_m, 'clearance_um': config.clearance_um}
