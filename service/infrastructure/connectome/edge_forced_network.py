"""Experimental propagation of explicitly scheduled edge-local events.

Forced sources are silent in the LIF solver, receive no feedback, and are not
reported as firing neurons. Edge events are model inputs, not physiological
spikes or evidence of connections between reconstructed SWC fragments.
"""

from __future__ import annotations

import numpy as np

from service.domain import target_response_limits
from service.domain.target_response_limits import can_capture_targets, network_sample_ticks
from service.infrastructure.connectome.kernel import advance, signed_weights


def run_edge_forced_network(graph, *, seed, duration_ms, forced_cell_ids, edge_events,
                            sample_cell_ids=None, sample_ticks=None, capture_sparse_delta=False):
    """Run the existing LIF graph with explicitly bounded per-edge event counts."""
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Invalid seed")
    if type(duration_ms) is not int or not 1 <= duration_ms <= 1000:
        raise ValueError("Invalid duration")
    if type(capture_sparse_delta) is not bool:
        raise ValueError("Invalid sparse delta option")
    if (
        not isinstance(forced_cell_ids, list | tuple)
        or not forced_cell_ids
        or any(type(value) is not int or value <= 0 for value in forced_cell_ids)
        or len(set(forced_cell_ids)) != len(forced_cell_ids)
    ):
        raise ValueError("Invalid forced cell IDs")
    positions = np.searchsorted(graph.ids, forced_cell_ids)
    if any(
        pos >= graph.size or int(graph.ids[pos]) != body
        for pos, body in zip(positions, forced_cell_ids, strict=True)
    ):
        raise ValueError("Forced cell is not registered in graph")
    if not isinstance(edge_events, list) or len(edge_events) > 1_000_000:
        raise ValueError("Invalid or oversized edge schedule")
    sampled_positions = None
    if sample_cell_ids is not None:
        ticks = list(range(duration_ms + 1)) if sample_ticks is None else sample_ticks
        if (not isinstance(sample_cell_ids, list | tuple)
                or len(sample_cell_ids) > graph.size
                or not isinstance(ticks, list) or len(ticks) < 2
                or any(type(tick) is not int for tick in ticks)
                or ticks[0] != 0 or ticks[-1] != duration_ms
                or any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))
                or not can_capture_targets(len(sample_cell_ids), len(ticks) - 1)
                or any(type(value) is not int or value <= 0 for value in sample_cell_ids)
                or len(set(sample_cell_ids)) != len(sample_cell_ids)):
            raise ValueError("Invalid sampled cell IDs")
        sampled_positions = np.searchsorted(graph.ids, sample_cell_ids)
        if any(pos >= graph.size or int(graph.ids[pos]) != body
               for pos, body in zip(sampled_positions, sample_cell_ids, strict=True)):
            raise ValueError("Sampled cell is not registered in graph")
    source_positions = dict(zip(forced_cell_ids, map(int, positions), strict=True))
    schedule = [[] for _ in range(duration_ms)]
    seen = set()
    for item in edge_events:
        if (
            not isinstance(item, dict)
            or set(item) != {"source_id", "target_id", "tick", "count"}
            or any(type(item[key]) is not int for key in item)
        ):
            raise ValueError("Invalid edge event")
        source, target, tick, count = (
            item[key] for key in ("source_id", "target_id", "tick", "count")
        )
        if source not in source_positions or not 1 <= tick <= duration_ms or count <= 0:
            raise ValueError("Invalid edge event")
        target_pos = int(np.searchsorted(graph.ids, target))
        if target_pos >= graph.size or int(graph.ids[target_pos]) != target:
            raise ValueError("Edge target is not registered")
        pos = source_positions[source]
        start, end = int(graph.ptr[pos]), int(graph.ptr[pos + 1])
        matches = np.flatnonzero(graph.posts[start:end] == target_pos)
        if len(matches) != 1 or count > int(graph.counts[start + matches[0]]):
            raise ValueError("Edge is missing, ambiguous or exceeds registered synapses")
        key = (source, target, tick)
        if key in seen:
            raise ValueError("Duplicate edge event")
        seen.add(key)
        weight = float(count) * int(graph.signs[pos]) * 0.075
        schedule[tick - 1].append((target_pos, weight))

    n = graph.size
    voltage = np.random.default_rng(seed).uniform(0, 2, n).astype(np.float32)
    current, refractory = np.zeros(n, np.float32), np.zeros(n, np.int16)
    queue, drive = np.zeros((3, n), np.float32), np.zeros(n, np.float32)
    silenced = np.zeros(n, dtype=np.bool_)
    silenced[positions] = True
    weights = signed_weights(graph.ptr, graph.counts, graph.signs, 0.075)
    counts, spikes, times = np.zeros(n, dtype=np.int32), [], []
    if capture_sparse_delta:
        quiet_voltage = voltage.copy()
        quiet_current = np.zeros(n, np.float32)
        quiet_refractory = np.zeros(n, np.int16)
        quiet_queue = np.zeros((3, n), np.float32)
        sparse_offsets, sparse_indices, sparse_values = [0, 0], [], []
        sparse_count, sparse_overflow = 0, False
    samples = None
    if sampled_positions is not None:
        samples = np.empty((len(ticks), len(sampled_positions)), dtype=np.float32)
        samples[0] = voltage[sampled_positions]
        next_sample = 1
    for clock, events in enumerate(schedule):
        fired = advance(
            graph.ptr,
            graph.posts,
            weights,
            voltage,
            current,
            refractory,
            queue,
            clock,
            drive,
            1,
            silenced,
        )
        if capture_sparse_delta:
            advance(graph.ptr, graph.posts, weights, quiet_voltage, quiet_current,
                    quiet_refractory, quiet_queue, clock, drive, 1, silenced)
            if not np.isfinite(quiet_voltage).all() or not np.isfinite(quiet_current).all():
                raise ValueError("Non-finite control state")
            if not sparse_overflow:
                delta = voltage - quiet_voltage
                changed = np.flatnonzero(delta).astype(np.int32)
                sparse_count += len(changed)
                if sparse_count > target_response_limits.MAX_TARGET_RESPONSE_VALUES:
                    sparse_overflow = True
                    sparse_offsets, sparse_indices, sparse_values = [], [], []
                else:
                    sparse_indices.append(changed)
                    sparse_values.append(delta[changed])
                    sparse_offsets.append(sparse_count)
        for target, weight in events:
            queue[(clock + 2) % 3, target] += weight
        counts += fired
        active = np.flatnonzero(fired).astype(np.int32)
        if len(active):
            spikes.append(active)
            times.append(np.full(len(active), clock + 1, np.float32))
        if not np.isfinite(voltage).all() or not np.isfinite(current).all():
            raise ValueError("Non-finite graph state")
        if samples is not None and next_sample < len(ticks) and clock + 1 == ticks[next_sample]:
            samples[next_sample] = voltage[sampled_positions]
            next_sample += 1
    result = {
        "spike_neurons": np.concatenate(spikes) if spikes else np.empty(0, np.int32),
        "spike_times_ms": np.concatenate(times) if times else np.empty(0, np.float32),
        "counts": counts,
        "final_voltage_relative_mv": voltage,
        "final_synaptic_drive_mv": current,
        "forced_cell_ids": list(forced_cell_ids),
        "metadata": {
            "seed": seed,
            "duration_ms": duration_ms,
            "step_ms": 1.0,
            "synaptic_delay_ms": 2.0,
            "graph": graph.provenance,
            "interpretation": "one-way model edge inputs; source cells are silenced, "
            "no source-cell spikes or biological validity inferred",
        },
    }
    if samples is not None:
        result['sampled_voltage_relative_mv'] = samples
        result['sampled_cell_ids'] = list(sample_cell_ids)
        result['sampled_time_ms'] = np.asarray(ticks, dtype=np.float32)
    if capture_sparse_delta:
        if sparse_overflow:
            result['sparse_delta'] = {'status': 'limit_exceeded'}
        else:
            result['sparse_delta'] = {
                'status': 'recorded', 'offsets': np.asarray(sparse_offsets, dtype=np.uint32),
                'indices': (np.concatenate(sparse_indices) if sparse_indices
                            else np.empty(0, np.int32)),
                'values': (np.concatenate(sparse_values) if sparse_values
                           else np.empty(0, np.float32)),
            }
    return result


def run_fragment_edge_network(graph, diagnostics, *, seed, duration_ms, max_distance_um):
    """Apply an explicitly constrained fragment schedule to its matching graph."""
    from service.infrastructure.stimulation.fragment_output_diagnostics import (
        fragment_edge_schedule,
    )

    schedule = fragment_edge_schedule(
        diagnostics, max_distance_um=max_distance_um, duration_ms=duration_ms
    )
    if schedule["graph_sha256"] != graph.provenance.get("manifest_sha256"):
        raise ValueError("Fragment schedule and graph identity differ")
    result = run_edge_forced_network(
        graph,
        seed=seed,
        duration_ms=duration_ms,
        forced_cell_ids=[schedule["source_id"]],
        edge_events=schedule["edge_events"],
    )
    return {
        "network": result,
        "schedule": schedule,
        "interpretation": "experimental fragment-local inputs; no inter-fragment connectivity "
        "or source-cell spike inferred",
    }


def run_fragment_population_network(graph, diagnostics, *, seed, duration_ms, max_distance_um,
                                    capture_target_response=False, response_scope='direct-targets',
                                    allow_partial_geometry=False):
    """Couple a bounded set of independent sources without asserting full coverage."""
    from service.infrastructure.stimulation.fragment_output_diagnostics import (
        fragment_edge_schedule,
    )

    if (not isinstance(diagnostics, list) or not 1 <= len(diagnostics) <= 256
            or type(capture_target_response) is not bool
            or type(allow_partial_geometry) is not bool
            or response_scope not in ('direct-targets', 'network')):
        raise ValueError("Invalid fragment source population")
    schedules = [
        fragment_edge_schedule(item, max_distance_um=max_distance_um, duration_ms=duration_ms,
                               allow_partial_geometry=allow_partial_geometry)
        for item in diagnostics
    ]
    if any(item["graph_sha256"] != graph.provenance.get("manifest_sha256") for item in schedules):
        raise ValueError("Fragment schedules and graph identity differ")
    if any(
        (item["simulation_sha256"], item["threshold_mv"])
        != (schedules[0]["simulation_sha256"], schedules[0]["threshold_mv"])
        for item in schedules
    ):
        raise ValueError("Fragment sources have different stimulation or threshold")
    source_ids = [item["source_id"] for item in schedules]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("Duplicate fragment source")
    events = [event for item in schedules for event in item["edge_events"]]
    excluded = set(source_ids)
    targets = ([int(body) for body in graph.ids if int(body) not in excluded]
               if response_scope == 'network'
               else sorted({event['target_id'] for event in events} - excluded))
    ticks = (network_sample_ticks(len(targets), duration_ms) if response_scope == 'network'
             else list(range(duration_ms + 1)) if can_capture_targets(len(targets), duration_ms)
             else None)
    sampled = targets if capture_target_response and ticks is not None else None
    result = run_edge_forced_network(
        graph, seed=seed, duration_ms=duration_ms, forced_cell_ids=source_ids, edge_events=events,
        sample_cell_ids=sampled, sample_ticks=ticks if sampled is not None else None,
        capture_sparse_delta=capture_target_response and response_scope == 'network',
    )
    output = {
        "network": result,
        "schedules": schedules,
        "source_ids": source_ids,
        "coverage": "explicitly supplied sources only; not necessarily the whole graph",
        "interpretation": "independent fragment-local inputs without inter-fragment "
        "connections or source-cell spikes; no network feedback to sources",
    }
    if capture_target_response:
        if sampled is None:
            output['target_response'] = {
                'status': (('no_network_targets' if response_scope == 'network'
                            else 'no_direct_targets') if not targets else 'target_limit_exceeded'),
                'target_count': len(targets),
            }
        else:
            control = run_edge_forced_network(
                graph, seed=seed, duration_ms=duration_ms, forced_cell_ids=source_ids,
                edge_events=[], sample_cell_ids=sampled, sample_ticks=ticks,
            )
            output['target_response'] = {
                'status': 'recorded',
                'target_count': len(sampled),
                'target_ids': sampled,
                'time_ms': result['sampled_time_ms'],
                'active_relative_mv': result['sampled_voltage_relative_mv'],
                'control_relative_mv': control['sampled_voltage_relative_mv'],
                'delta_relative_mv': (result['sampled_voltage_relative_mv']
                                      - control['sampled_voltage_relative_mv']),
                'interpretation': 'paired LIF relative voltage at direct targets, not electrode '
                                  'recording or validated physiology',
            }
        if response_scope == 'network':
            output['target_response']['scope'] = 'network-excluding-forced-sources'
    return output
