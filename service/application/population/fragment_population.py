"""Experimental one-way fragment-local STIM, recording and graph propagation.

This is a bounded subset model. Independently simulated fragments are not
connected, and the recorded currents do not include downstream graph cells.
"""

from __future__ import annotations

import math
import re

from service.domain.target_response_limits import network_sample_ticks
from service.infrastructure.connectome.edge_forced_network import run_fragment_population_network
from service.infrastructure.stimulation.fragment_output_diagnostics import (
    fragment_edge_schedule,
    preflight_outgoing_fragment_geometry,
    registered_outgoing_fragment_diagnostics,
)
from service.infrastructure.stimulation.network_recording import record_independent_cells
from service.infrastructure.stimulation.swc_reference import simulate_registered_swc_reference


def run_fragment_population(
    graph,
    index,
    directories,
    *,
    source_ids,
    simulation_parameters,
    electrode_um,
    reference_um,
    source_model,
    threshold_mv,
    max_distance_um,
    seed,
    provenance_sink=None,
    allow_partial_geometry=False,
    progress=None,
):
    """Solve selected cells once for recording and paired fragment-local diagnostics."""
    if type(allow_partial_geometry) is not bool:
        raise ValueError("Invalid partial geometry setting")
    if (
        not isinstance(source_ids, list)
        or not 1 <= len(source_ids) <= 256
        or any(type(body) is not int or body <= 0 for body in source_ids)
        or len(set(source_ids)) != len(source_ids)
    ):
        raise ValueError("Invalid fragment source population")
    if (
        not isinstance(simulation_parameters, dict)
        or simulation_parameters.get("allow_disconnected") is not True
        or any(
            key in simulation_parameters
            for key in ("synaptic_events", "record_membrane_current", "field_coupling",
                        "expected_morphology_sha256")
        )
    ):
        raise ValueError("Explicit independent-fragment simulation settings required")
    duration = simulation_parameters.get("duration_ms")
    current = simulation_parameters.get("current_na")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or not float(duration).is_integer()
        or not 1 <= duration <= 1000
        or isinstance(current, bool)
        or not isinstance(current, int | float)
        or not math.isfinite(current)
    ):
        raise ValueError("Invalid stimulation duration or current")
    duration = int(duration)
    geometry, unresolved = {}, []
    for count, body in enumerate(source_ids, 1):
        try:
            geometry[body] = preflight_outgoing_fragment_geometry(
                index, graph, body, directories, max_distance_um=max_distance_um,
                **({'allow_partial_geometry': True} if allow_partial_geometry else {}),
            )
        except ValueError as exc:
            match = re.fullmatch(
                r"Unresolved geometric candidate: source ([1-9][0-9]{0,18}), "
                r"([1-9][0-9]*)/([1-9][0-9]*) graph synapses outside "
                r"[0-9.eE+-]+ um; maximum [0-9.eE+-]+ um", str(exc),
            )
            if (not match or int(match[1]) != body or int(match[2]) > int(match[3])
                    or int(match[3]) > 999999999):
                raise
            unresolved.append((body, int(match[2]), int(match[3]), str(exc)))
        if progress is not None:
            progress('geometry', count, len(source_ids))
    if len(unresolved) == 1:
        raise ValueError(unresolved[0][3])
    if unresolved:
        # Keep the resulting, validated backend error below its 500-character
        # database limit while reporting as many incompatible cells as possible.
        entries = []
        for body, outside, total, _ in unresolved:
            entry = f'{body}:{outside}:{total}'
            if len(','.join([*entries, entry])) > 400:
                break
            entries.append(entry)
        displayed = ','.join(entries)
        raise ValueError(f'Unresolved geometric candidates: {displayed}; '
                         f'omitted:{len(unresolved) - len(entries)}')
    diagnostics = []

    def solutions():
        for count, body in enumerate(source_ids, 1):
            active, proof = simulate_registered_swc_reference(
                body, directories, **simulation_parameters,
                expected_morphology_sha256=geometry[body]["morphology_sha256"],
            )
            control, control_proof = simulate_registered_swc_reference(
                body,
                directories,
                **{**simulation_parameters, "current_na": 0.0},
                record_membrane_current=False,
                expected_morphology_sha256=proof["morphology_sha256"],
            )
            diagnostic = registered_outgoing_fragment_diagnostics(
                index,
                graph,
                body,
                directories,
                active,
                control,
                proof,
                control_proof,
                threshold_mv=threshold_mv,
                duration_ms=duration,
            )
            if allow_partial_geometry:
                for row in diagnostic['candidates']:
                    if (row['included_in_graph']
                            and row['centerline_distance_um'] > max_distance_um):
                        # A voltage from the nearest unrelated segment cannot
                        # establish whether this synapse crossed threshold.
                        row['status'] = 'geometry_unresolved'
                        for key in ('stimulated_ticks_ms', 'control_ticks_ms',
                                    'stimulated_crossing_intervals', 'control_crossing_intervals',
                                    'max_stimulated_mv', 'max_control_mv', 'max_abs_delta_mv'):
                            row[key] = None
            # Stop at the first unresolved source rather than spending time
            # solving the remaining cells and failing only after recording.
            fragment_edge_schedule(
                diagnostic, max_distance_um=max_distance_um, duration_ms=duration,
                allow_partial_geometry=allow_partial_geometry,
            )
            diagnostics.append(diagnostic)
            del control
            if progress is not None:
                progress('cells', count, len(source_ids))
            yield active, proof

    recording = record_independent_cells(
        solutions(),
        electrode_um,
        reference_um,
        source_model=source_model,
        **({"provenance_sink": provenance_sink} if provenance_sink is not None else {}),
    )
    if progress is not None:
        progress('network', 0, 0)
    network = run_fragment_population_network(
        graph, diagnostics, seed=seed, duration_ms=duration, max_distance_um=max_distance_um,
        capture_target_response=True,
        allow_partial_geometry=allow_partial_geometry,
        response_scope=('network' if network_sample_ticks(graph.size - len(source_ids), duration)
                        else 'direct-targets'),
    )
    return {
        "recording": recording,
        "network": network,
        "diagnostics": diagnostics,
        "coverage": "explicitly supplied sources only; not a full-network physical recording",
        "interpretation": "independent fragments, uncalibrated edge propagation, "
        "no inter-fragment connectivity or feedback inferred",
    }
