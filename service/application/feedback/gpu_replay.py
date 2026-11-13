"""Experimental bridge from feedback requests to registered GPU batches."""

import math

from service.domain.pulse_train import pulse_train
from service.infrastructure.stimulation.experimental_gpu.registered_batch import (
    run_registered_batch,
)
from service.infrastructure.stimulation.experimental_gpu.waveform import kernel_midpoint_samples


def replay_gpu_batch(
    requests, directories, simulation, *, output_budget_bytes, progress=None, check_cancelled=None,
    allow_table_clamp=False, geometry_cache=None
):
    """Return recording-compatible GPU results for explicitly prepared cells.

    The caller must validate the graph, feedback schedule, morphology hashes
    and endpoint-discretization evidence before making requests. Disconnected
    fragments are electrically independent. Only the currently validated fixed
    HH parameters are supported.
    This independent-cell replay is not itself a coupled network simulation.
    """
    if not isinstance(simulation, dict):
        raise ValueError("Invalid GPU replay configuration")
    expected = {
        "source_um",
        "return_um",
        "current_na",
        "conductivity_s_m",
        "clearance_um",
        "duration_ms",
        "dt_ms",
        "pulse_start_ms",
        "pulse_end_ms",
        "rise_time_ms",
        "interphase_gap_ms",
        "pulse_shape",
        "nseg_per_edge",
        "allow_disconnected",
    }
    if (
        not expected <= set(simulation)
        or set(simulation) - expected not in (set(), {"pulse_count", "pulse_interval_ms"})
        or type(simulation["dt_ms"]) not in (int, float)
        or simulation["dt_ms"] not in (0.025, 0.05)
        or type(simulation["nseg_per_edge"]) is not int
        or simulation["nseg_per_edge"] != 1
        or type(simulation["allow_disconnected"]) is not bool
    ):
        raise ValueError("Unsupported GPU replay configuration")
    duration = simulation["duration_ms"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or duration <= 0
        or not math.isclose(round(duration / simulation["dt_ms"]) * simulation["dt_ms"],
                            duration, rel_tol=0, abs_tol=1e-9)
    ):
        raise ValueError("Invalid GPU replay duration")
    raw_count = simulation.get("pulse_count")
    interval = simulation.get("pulse_interval_ms")
    if (raw_count is None) != (interval is None) or (
        raw_count is not None and (type(raw_count) is not int or not 2 <= raw_count <= 1000)
    ):
        raise ValueError("Invalid GPU pulse train")
    count = raw_count or 1
    times, levels = pulse_train(
        start_ms=simulation["pulse_start_ms"],
        end_ms=simulation["pulse_end_ms"],
        rise_ms=simulation["rise_time_ms"],
        interphase_gap_ms=simulation["interphase_gap_ms"],
        shape=simulation["pulse_shape"],
        duration_ms=duration,
        count=count,
        interval_ms=interval,
    )
    dt_ms = simulation["dt_ms"]
    waveform = kernel_midpoint_samples(times, levels, dt_ms=dt_ms, steps=round(duration / dt_ms))
    config = {
        key: simulation[key]
        for key in (
            "source_um",
            "return_um",
            "current_na",
            "conductivity_s_m",
            "clearance_um",
            "duration_ms",
            "pulse_start_ms",
            "pulse_end_ms",
            "rise_time_ms",
            "interphase_gap_ms",
            "pulse_shape",
        )
    }
    if count > 1:
        config.update(pulse_count=count, pulse_interval_ms=interval)
    return run_registered_batch(
        requests,
        directories,
        waveform,
        source_um=simulation["source_um"],
        return_um=simulation["return_um"],
        current_na=simulation["current_na"],
        conductivity_s_m=simulation["conductivity_s_m"],
        clearance_um=simulation["clearance_um"],
        output_budget_bytes=output_budget_bytes,
        recording_config=config,
        progress=progress,
        check_cancelled=check_cancelled,
        dt_ms=dt_ms,
        allow_table_clamp=allow_table_clamp,
        geometry_cache=geometry_cache,
    )


def iter_gpu_replay_batches(requests, directories, simulation, *, max_cells,
                            output_budget_bytes, allow_table_clamp=False, geometry_cache=None,
                            progress=None, check_cancelled=None):
    """Yield ordered results in bounded groups after each group has completed.

    The bound limits the number of prepared cells and result objects retained
    by this iterator, not their total bytes or the solver's complete RAM/VRAM
    usage. Progress counts completed cells, not time or simulated steps.
    Callers must not collect the iterator when they require bounded memory.
    """
    if (not isinstance(requests, list) or not requests
            or type(max_cells) is not int or max_cells < 1
            or (progress is not None and not callable(progress))
            or (check_cancelled is not None and not callable(check_cancelled))
            or any(not isinstance(item, dict) or type(item.get('id')) is not int
                   or item['id'] <= 0 for item in requests)
            or len({item['id'] for item in requests}) != len(requests)):
        raise ValueError('Invalid streaming GPU replay request')
    for start in range(0, len(requests), max_cells):
        if check_cancelled is not None:
            check_cancelled()
        group = requests[start:start + max_cells]
        output = replay_gpu_batch(group, directories, simulation,
            output_budget_bytes=output_budget_bytes, allow_table_clamp=allow_table_clamp,
            geometry_cache=geometry_cache, check_cancelled=check_cancelled)
        if (len(output) != len(group)
                or [row.get('id') for row in output] != [row['id'] for row in group]):
            raise ValueError('Incomplete or reordered GPU replay group')
        for row in output:
            yield row
        del row, output
        if progress is not None:
            progress(start + len(group), len(requests))
