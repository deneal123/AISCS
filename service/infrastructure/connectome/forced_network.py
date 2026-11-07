"""Experimental one-way coupling of explicit cell events into the registered LIF graph.

The source cells are clamped to an externally computed spike schedule. They do
not receive network feedback. Neither the graph parameters nor the threshold
used to extract events are calibrated Drosophila physiology.
"""

from __future__ import annotations

import math

import numpy as np

from service.infrastructure.connectome.kernel import advance, signed_weights


def threshold_crossing_ticks(time_ms, voltage_mv, *, threshold_mv, duration_ms):
    """Map upward crossings to the next 1 ms graph tick without inventing timing.

    The voltage is a caller-selected compartment trace. Choosing a compartment
    and threshold is a modelling assumption, not an anatomical validation.
    Multiple crossings in one graph tick are rejected rather than merged.
    Times within 1e-9 ms of an integer are snapped to that integer to absorb
    solver clock roundoff; other crossings are always rounded forward.
    If the two samples bracketing a crossing straddle a tick boundary, the
    discretized event time is ambiguous and is rejected rather than guessed.
    """
    time = np.asarray(time_ms, dtype=np.float64)
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    if (time.ndim != 1 or len(time) < 2 or voltage.shape != time.shape
            or not np.isfinite(time).all() or not np.isfinite(voltage).all()
            or time[0] != 0 or np.any(np.diff(time) <= 0)
            or isinstance(threshold_mv, bool | np.bool_) or not math.isfinite(threshold_mv)
            or type(duration_ms) is not int or duration_ms < 1
            or time[-1] < duration_ms - 1e-9):
        raise ValueError("Invalid cell trace or crossing parameters")
    indices = np.flatnonzero((voltage[:-1] < threshold_mv) & (voltage[1:] >= threshold_mv)) + 1
    if voltage[0] >= threshold_mv:
        raise ValueError("Initial voltage is already above the crossing threshold")
    crossing_times = time[indices]
    if np.any(crossing_times > duration_ms + 1e-9):
        raise ValueError("Cell trace contains crossings outside the graph interval")
    def snap(values):
        nearest = np.rint(values)
        return np.where(np.abs(values - nearest) <= 1e-9, nearest, values)

    snapped = snap(crossing_times)
    snapped = np.where(snapped == 0, crossing_times, snapped)
    ticks = np.ceil(snapped).astype(np.int64)
    earliest = np.floor(snap(time[indices - 1])).astype(np.int64) + 1
    if np.any(earliest != ticks):
        raise ValueError("Threshold crossing spans a graph tick boundary; refine the time step")
    if len(np.unique(ticks)) != len(ticks):
        raise ValueError("Multiple cell events fall within one graph tick")
    return ticks


def threshold_crossing_intervals(time_ms, voltage_mv, *, threshold_mv, duration_ms):
    """Keep bracketing samples as bounds, without estimating a crossing within them."""
    ticks = threshold_crossing_ticks(
        time_ms, voltage_mv, threshold_mv=threshold_mv, duration_ms=duration_ms)
    time = np.asarray(time_ms, dtype=np.float64)
    voltage = np.asarray(voltage_mv, dtype=np.float64)
    indices = np.flatnonzero((voltage[:-1] < threshold_mv) & (voltage[1:] >= threshold_mv)) + 1
    return [{'lower_ms': float(time[index - 1]), 'upper_ms': float(time[index]),
             'tick_ms': int(tick)} for index, tick in zip(indices, ticks, strict=True)]


def validate_crossing_intervals(intervals, ticks, *, duration_ms):
    """Check stored bounds against the registered tick; legacy schedules may omit bounds."""
    if not isinstance(intervals, list) or len(intervals) != len(ticks):
        raise ValueError('Invalid crossing interval count')
    previous = -1.0
    def snap(value):
        rounded = round(value)
        return float(rounded) if abs(value - rounded) <= 1e-9 else value
    for interval, tick in zip(intervals, ticks, strict=True):
        if not isinstance(interval, dict) or set(interval) != {'lower_ms', 'upper_ms', 'tick_ms'}:
            raise ValueError('Invalid crossing interval')
        lower, upper = interval['lower_ms'], interval['upper_ms']
        if (type(lower) not in (int, float) or type(upper) not in (int, float)
                or not math.isfinite(lower) or not math.isfinite(upper)
                or not 0 <= lower < upper <= duration_ms + 1e-9 or lower < previous
                or type(interval['tick_ms']) is not int or interval['tick_ms'] != tick
                or math.floor(snap(lower)) + 1 != tick
                or math.ceil(snap(upper) or upper) != tick):
            raise ValueError('Crossing interval does not match graph tick')
        previous = upper


def run_forced_network(graph, *, seed, duration_ms, forced_cell_ids, events,
                       sample_cell_ids=None):
    """Propagate explicit source-cell spikes through the LIF graph, one-way only.

    Event times are integer milliseconds at tick ends, matching ``run_network``.
    Every forced cell is silenced in the LIF solver, including when its schedule
    is empty; incoming graph activity cannot alter its supplied trace. Output
    weights and two-millisecond queue delivery match the existing LIF kernel.
    """
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Invalid seed")
    if type(duration_ms) is not int or not 1 <= duration_ms <= 1000:
        raise ValueError("Invalid duration")
    if (not isinstance(forced_cell_ids, list | tuple) or not forced_cell_ids
            or any(type(value) is not int or value <= 0 for value in forced_cell_ids)
            or len(set(forced_cell_ids)) != len(forced_cell_ids)):
        raise ValueError("Invalid forced cell IDs")
    positions = np.searchsorted(graph.ids, forced_cell_ids)
    if any(pos >= graph.size or int(graph.ids[pos]) != body
           for pos, body in zip(positions, forced_cell_ids, strict=True)):
        raise ValueError("Forced cell is not registered in graph")
    if not isinstance(events, dict) or set(events) != set(forced_cell_ids):
        raise ValueError("An explicit schedule is required for every forced cell")
    sample_positions = None
    if sample_cell_ids is not None:
        if (not isinstance(sample_cell_ids, list | tuple) or not sample_cell_ids
                or any(type(value) is not int or value <= 0 for value in sample_cell_ids)
                or len(set(sample_cell_ids)) != len(sample_cell_ids)
                or len(sample_cell_ids) * (duration_ms + 1) > 4_000_000):
            raise ValueError("Invalid or oversized sampled cell selection")
        sample_positions = np.searchsorted(graph.ids, sample_cell_ids)
        if any(pos >= graph.size or int(graph.ids[pos]) != body
               for pos, body in zip(sample_positions, sample_cell_ids, strict=True)):
            raise ValueError("Sampled cell is not registered in graph")
    schedule = [[] for _ in range(duration_ms)]
    for body, position in zip(forced_cell_ids, positions, strict=True):
        ticks = events[body]
        if (not isinstance(ticks, list | tuple | np.ndarray)
                or any(isinstance(tick, bool | np.bool_)
                       or not isinstance(tick, int | np.integer)
                       or not 1 <= tick <= duration_ms for tick in ticks)
                or any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))):
            raise ValueError("Invalid forced event schedule")
        for tick in ticks:
            schedule[int(tick) - 1].append(int(position))
    n = graph.size
    voltage = np.random.default_rng(seed).uniform(0, 2, n).astype(np.float32)
    current, refractory = np.zeros(n, np.float32), np.zeros(n, np.int16)
    queue, drive = np.zeros((3, n), np.float32), np.zeros(n, np.float32)
    silenced = np.zeros(n, dtype=np.bool_)
    silenced[positions] = True
    weights = signed_weights(graph.ptr, graph.counts, graph.signs, 0.075)
    counts = np.zeros(n, dtype=np.int32)
    samples = None
    if sample_positions is not None:
        samples = np.empty((duration_ms + 1, len(sample_positions)), dtype=np.float32)
        samples[0] = voltage[sample_positions]
    spikes, times = [], []
    for clock, forced in enumerate(schedule):
        fired = advance(graph.ptr, graph.posts, weights, voltage, current, refractory,
                        queue, clock, drive, 1, silenced)
        for source in forced:
            start, end = int(graph.ptr[source]), int(graph.ptr[source + 1])
            np.add.at(queue[(clock + 2) % 3], graph.posts[start:end], weights[start:end])
            fired[source] = 1
        counts += fired
        active = np.flatnonzero(fired).astype(np.int32)
        if len(active):
            spikes.append(active)
            times.append(np.full(len(active), clock + 1, np.float32))
        if not np.isfinite(voltage).all() or not np.isfinite(current).all():
            raise ValueError("Non-finite graph state")
        if samples is not None:
            samples[clock + 1] = voltage[sample_positions]
    result = {
        "spike_neurons": np.concatenate(spikes) if spikes else np.empty(0, np.int32),
        "spike_times_ms": np.concatenate(times) if times else np.empty(0, np.float32),
        "counts": counts,
        "final_voltage_relative_mv": voltage,
        "final_synaptic_drive_mv": current,
        "forced_cell_ids": list(forced_cell_ids),
        "metadata": {"seed": seed, "duration_ms": duration_ms, "step_ms": 1.0,
                     "synaptic_delay_ms": 2.0, "graph": graph.provenance,
                     "interpretation": "one-way forced cell events; no feedback to source cells, "
                                       "uncalibrated LIF dynamics and signs"},
    }
    if samples is not None:
        result['sampled_voltage_relative_mv'] = samples
        result['sampled_cell_ids'] = list(sample_cell_ids)
        result['sampled_time_ms'] = np.arange(duration_ms + 1, dtype=np.float32)
    return result


def contrast_forced_network(graph, *, seed, duration_ms, forced_cell_ids, events,
                            sample_cell_ids):
    """Compare sampled LIF states to the same seeded network without input events.

    The result is a model-state contrast, not a measured potential or spike.
    All source cells are silenced in both runs; only their event schedules differ.
    """
    arguments = dict(seed=seed, duration_ms=duration_ms, forced_cell_ids=forced_cell_ids,
                     sample_cell_ids=sample_cell_ids)
    active = run_forced_network(graph, events=events, **arguments)
    control = run_forced_network(graph, events={body: [] for body in forced_cell_ids}, **arguments)
    return {
        'sampled_cell_ids': active['sampled_cell_ids'],
        'sampled_time_ms': active['sampled_time_ms'],
        'active_voltage_relative_mv': active['sampled_voltage_relative_mv'],
        'control_voltage_relative_mv': control['sampled_voltage_relative_mv'],
        'voltage_difference_mv': (active['sampled_voltage_relative_mv']
                                  - control['sampled_voltage_relative_mv']),
        'active_spike_neurons': active['spike_neurons'],
        'active_spike_times_ms': active['spike_times_ms'],
        'control_spike_neurons': control['spike_neurons'],
        'control_spike_times_ms': control['spike_times_ms'],
    }
