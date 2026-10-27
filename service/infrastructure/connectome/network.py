"""Whole registered CNS execution; LIF drive is not a transmembrane current in nA."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from service.infrastructure.connectome.dataset import SparseGraph
from service.infrastructure.connectome.kernel import advance, signed_weights


@dataclass
class NetworkRun:
    spike_neurons: np.ndarray
    spike_times_ms: np.ndarray
    final_voltage_relative_mv: np.ndarray
    final_synaptic_drive_mv: np.ndarray
    counts: np.ndarray
    input_indices: np.ndarray
    projected_events: list[dict]
    metadata: dict


def run_network(
    graph: SparseGraph,
    *,
    seed: int,
    stimulus: str,
    region: str,
    duration_ms: float,
    excitability: float = 1.0,
    adaptation: float = 0.3,
) -> NetworkRun:
    if (
        stimulus not in ("none", "weak", "strong")
        or not np.isfinite(duration_ms)
        or not float(duration_ms).is_integer()
        or not 1 <= duration_ms <= 1000
    ):
        raise ValueError("Unsupported whole-CNS stimulus or non-integer millisecond duration")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Invalid whole-CNS seed")
    if (
        not np.isfinite([excitability, adaptation]).all()
        or not 0.7 <= excitability <= 1.3
        or not 0 <= adaptation <= 1
    ):
        raise ValueError("Invalid network parameters")
    started = perf_counter()
    inputs, groups = graph.stimulus_indices(region), graph.bridge_groups()
    n = graph.size
    voltage = np.random.default_rng(seed).uniform(0, 2, n).astype(np.float32)
    current, refractory = np.zeros(n, np.float32), np.zeros(n, np.int16)
    queue, drive = np.zeros((3, n), np.float32), np.zeros(n, np.float32)
    weights = signed_weights(graph.ptr, graph.counts, graph.signs, 0.075)
    emitted, times, projected = [], [], []
    total = np.zeros(n, dtype=np.int32)
    strength = {"none": 0.0, "weak": 12.0, "strong": 36.0}[stimulus]
    for clock in range(int(duration_ms)):
        drive.fill(0)
        if 25 <= clock < duration_ms - 25:
            gain = 1 - adaptation * (1 - np.exp(-(clock - 25) / 80))
            drive[inputs] = strength * excitability * gain
        fired = advance(
            graph.ptr, graph.posts, weights, voltage, current, refractory, queue, clock, drive, 1
        )
        active = np.flatnonzero(fired).astype(np.int32)
        if len(active):
            emitted.append(active)
            times.append(np.full(len(active), clock + 1, np.float32))
        total += fired
        if clock + 2 < duration_ms:
            for cell, indices in enumerate(groups):
                count = int(fired[indices].sum())
                if count:
                    projected.append(
                        {
                            "cell_id": cell,
                            "time_ms": float(clock + 2),
                            "weight_us": min(0.02, count * 0.0005),
                            "source_population_spikes": count,
                        }
                    )
        if not np.isfinite(voltage).all() or not np.isfinite(current).all():
            raise ValueError("Non-finite whole-CNS state")
    spike_neurons = np.concatenate(emitted) if emitted else np.empty(0, np.int32)
    spike_times = np.concatenate(times) if times else np.empty(0, np.float32)
    outside = int(total.sum() - total[inputs].sum())
    return NetworkRun(
        spike_neurons,
        spike_times,
        voltage,
        current,
        total,
        inputs,
        projected,
        {
            **graph.provenance,
            "engine": "fly-arena-lif-1ms-2ms-delay-v1",
            "seed": seed,
            "duration_ms": duration_ms,
            "step_ms": 1.0,
            "synaptic_delay_ms": 2.0,
            "stimulus_region": region,
            "input_neurons": len(inputs),
            "input_population": (
                "cb_sensory / mechanosensory"
                if region == "head"
                else "vnc_sensory / mechanosensory_tactile"
            ),
            "active_neurons": int(np.count_nonzero(total)),
            "spikes": int(total.sum()),
            "spikes_outside_input_population": outside,
            "seconds": perf_counter() - started,
            "voltage_units": "mV relative to model rest",
            "synaptic_state_units": "mV drive proxy, not nA",
            "projection": {
                "groups": [
                    f"{section}_{side}" for section in ("T1", "T2", "T3") for side in ("L", "R")
                ],
                "group_sizes": [len(group) for group in groups],
                "rule": "author-defined population spikes -> ExpSyn conductance increments",
                "gain_us_per_spike": 0.0005,
                "maximum_event_us": 0.02,
                "delay_ms": 1.0,
                "not_a_reconstructed_cell_mapping": True,
            },
            "limitations": [
                "Engineering LIF defaults, not fitted physiology.",
                "Predicted transmitter signs lack receptor context.",
                "The registered selection excludes glia and unannotated fragments.",
                "Spikes are neither extracellular voltage nor subjective pain.",
            ],
        },
    )
