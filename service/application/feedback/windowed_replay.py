"""Internal bounded CUDA replay of already verified feedback requests."""

import time

import numpy as np

from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.experimental_gpu.waveform import kernel_midpoint_samples

from .windowed_outputs import solve_checked_windowed_feedback
from .windowed_prepare import prepare_windowed_sources


def replay_windowed_sources(requests, directories, simulation, diagnostics, *,
                            electrode_um, reference_um, threshold_mv, duration_ms,
                            max_source_distance_um, max_cells, output_budget_bytes,
                            window_steps, max_padding_ratio=2., allow_table_clamp=False,
                            progress=None, packing_cache=None, geometry_cache=None,
                            device_reduction=False, timing_sink=None, preparation_workers=1,
                            preparation_executor=None, cell_major=False):
    """Replay groups against a fixed schedule; the caller verifies graph identity.

    Retains only each group's output and final time series. The cell count and
    output budget are bounded, not total host/device memory. No publication,
    whole-network field or biological interpretation is implied.
    """
    if (not isinstance(requests, list) or not requests or not isinstance(simulation, dict)
            or not isinstance(diagnostics, dict) or type(max_cells) is not int or max_cells < 1
            or (progress is not None and not callable(progress))
            or (timing_sink is not None and not callable(timing_sink))
            or type(device_reduction) is not bool
            or type(cell_major) is not bool or (cell_major and not device_reduction)
            or type(preparation_workers) is not int or not 1 <= preparation_workers <= 8
            or (preparation_workers > 1 and geometry_cache is not None)
            or (preparation_executor is not None and preparation_workers == 1)
            or any(not isinstance(row, dict) or type(row.get('id')) is not int
                   or row['id'] <= 0 for row in requests)):
        raise ValueError('Invalid window replay request')
    ids = [row['id'] for row in requests]
    if len(ids) != len(set(ids)) or set(ids) != set(diagnostics):
        raise ValueError('Window replay source identity mismatch')
    if preparation_workers > 1 and preparation_executor is None:
        from service.infrastructure.stimulation.experimental_gpu.prepare_batches import (
            create_preparation_pool,
        )

        with create_preparation_pool(preparation_workers) as pool:
            return replay_windowed_sources(requests, directories, simulation, diagnostics,
                electrode_um=electrode_um, reference_um=reference_um, threshold_mv=threshold_mv,
                duration_ms=duration_ms, max_source_distance_um=max_source_distance_um,
                max_cells=max_cells, output_budget_bytes=output_budget_bytes,
                window_steps=window_steps, max_padding_ratio=max_padding_ratio,
                allow_table_clamp=allow_table_clamp, progress=progress, packing_cache=packing_cache,
                geometry_cache=geometry_cache, device_reduction=device_reduction,
                timing_sink=timing_sink, preparation_workers=preparation_workers,
                preparation_executor=pool, cell_major=cell_major)
    dt = simulation.get('dt_ms')
    if (type(dt) not in (int, float) or dt not in (.025, .05)
            or type(duration_ms) not in (int, float) or duration_ms <= 0
            or not np.isfinite(duration_ms)
            or not np.isclose(round(duration_ms / dt) * dt, duration_ms, rtol=0, atol=1e-9)
            or simulation.get('duration_ms') != duration_ms):
        raise ValueError('Invalid window replay time grid')
    raw_count = simulation.get('pulse_count')
    interval = simulation.get('pulse_interval_ms')
    if ((raw_count is None) != (interval is None)
            or (raw_count is not None and (type(raw_count) is not int
                                           or not 2 <= raw_count <= 1000))):
        raise ValueError('Invalid window replay pulse train')
    count = raw_count if raw_count is not None else 1
    times, levels = pulse_train(start_ms=simulation['pulse_start_ms'],
        end_ms=simulation['pulse_end_ms'], rise_ms=simulation['rise_time_ms'],
        interphase_gap_ms=simulation['interphase_gap_ms'], shape=simulation['pulse_shape'],
        duration_ms=duration_ms, count=count, interval_ms=interval)
    stimulus = kernel_midpoint_samples(times, levels, dt_ms=dt, steps=round(duration_ms / dt))
    keys = ('source_um', 'return_um', 'current_na', 'conductivity_s_m', 'clearance_um',
            'pulse_start_ms', 'pulse_end_ms', 'rise_time_ms', 'interphase_gap_ms',
            'pulse_shape', 'duration_ms', 'dt_ms')
    config = {key: simulation[key] for key in keys}
    if count > 1:
        config.update(pulse_count=count, pulse_interval_ms=interval)
    recording, sources, clamped = None, {}, []
    for start in range(0, len(ids), max_cells):
        group = requests[start:start + max_cells]
        group_ids = [row['id'] for row in group]
        started = time.perf_counter()
        prepared = prepare_windowed_sources(group, directories, simulation, max_cells=max_cells,
                                            geometry_cache=geometry_cache,
                                            preparation_workers=preparation_workers,
                                            preparation_executor=preparation_executor)
        if timing_sink is not None:
            timing_sink('prepare_sources', time.perf_counter() - started)
        result = solve_checked_windowed_feedback(prepared['cells'], prepared['provenance'],
            {body: diagnostics[body] for body in group_ids}, stimulus, prepared['hh_table'],
            stimulation_config=config, threshold_mv=threshold_mv, duration_ms=duration_ms,
            electrode_um=electrode_um, reference_um=reference_um,
            conductivity_s_m=simulation['conductivity_s_m'],
            clearance_um=simulation['clearance_um'],
            max_cells=max_cells, output_budget_bytes=output_budget_bytes, window_steps=window_steps,
            max_padding_ratio=max_padding_ratio, dt_ms=dt, allow_table_clamp=allow_table_clamp,
            max_source_distance_um=max_source_distance_um, packing_cache=packing_cache,
            device_reduction=device_reduction, timing_sink=timing_sink,
            **({'cell_major': True} if cell_major else {}))
        if list(result['sources']) != group_ids:
            raise ValueError('Incomplete or reordered window replay group')
        if recording is None:
            recording = {key: result[key].copy() for key in
                         ('time_ms', 'neural_uv', 'stimulus_fraction', 'stimulus_artifact_uv')}
        elif any(not np.array_equal(recording[key], result[key]) for key in
                 ('time_ms', 'stimulus_fraction', 'stimulus_artifact_uv')):
            raise ValueError('Inconsistent window replay stimulus or time grid')
        else:
            recording['neural_uv'] += result['neural_uv']
        sources.update(result['sources'])
        clamped.extend(result['table_clamped_cell_ids'])
        if progress is not None:
            progress(start + len(group), len(ids))
    recording['total_uv'] = recording['neural_uv'] + recording['stimulus_artifact_uv']
    if not np.isfinite(recording['total_uv']).all():
        raise ValueError('Non-finite window replay recording')
    return {'recording': recording, 'sources': sources,
            'table_clamped_cell_ids': clamped,
            'interpretation': 'experimental fixed-schedule source replay; not a network result'}
