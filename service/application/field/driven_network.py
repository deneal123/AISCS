"""Experimental field-to-cell-to-graph pipeline with explicit source locations.

This is an open-loop engineering model, not a coupled biophysical network or
validated prediction of stimulation. Source cells never receive graph feedback.
"""

from __future__ import annotations

import math
import re

import numpy as np

from service.infrastructure.connectome.forced_network import (
    run_forced_network,
    threshold_crossing_ticks,
)
from service.infrastructure.stimulation.network_recording import (
    acquire_independent_cells,
    record_independent_cells,
)
from service.infrastructure.stimulation.swc_reference import simulate_registered_swc_reference
from service.infrastructure.stimulation.threshold_diagnostics import (
    compartment_crossing_events,
    compartment_crossing_summary,
)


def run_field_driven_network(graph, directories, *, cells, simulation_parameters, seed,
                             recording=None, acquisition=None, solution_sink=None,
                             retain_compartment_crossings=False):
    """Apply one physical stimulus to selected SWCs, then inject their events.

    ``cells`` is a list of dictionaries containing the registered ``body_id``,
    a *preselected* SWC ``child_node_id`` and a voltage ``threshold_mv``. The
    Without an explicit fraction the trace is taken at the midpoint. An explicit
    fraction selects the nearest segment centre, which is reported separately.
    The same field and timing are used for every cell; full traces and provenance
    are returned so the event extraction can be independently checked.
    """
    if not isinstance(cells, list) or not cells:
        raise ValueError("At least one explicit source cell is required")
    if type(retain_compartment_crossings) is not bool:
        raise ValueError("Invalid compartment crossing retention setting")
    expected = {"body_id", "child_node_id", "threshold_mv"}
    for cell in cells:
        if (not isinstance(cell, dict) or not expected <= set(cell)
                or set(cell) - expected - {"sampling_fraction", "morphology_sha256"}
                or type(cell["body_id"]) is not int or cell["body_id"] <= 0
                or type(cell["child_node_id"]) is not int or cell["child_node_id"] <= 0
                or isinstance(cell["threshold_mv"], bool | np.bool_)
                or not isinstance(cell["threshold_mv"], int | float)
                or not math.isfinite(cell["threshold_mv"])):
            raise ValueError("Invalid explicit source cell")
        sha = cell.get("morphology_sha256")
        if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)):
            raise ValueError("Invalid source morphology digest")
        fraction = cell.get("sampling_fraction")
        if fraction is not None and (isinstance(fraction, bool | np.bool_)
                                     or not isinstance(fraction, int | float)
                                     or not math.isfinite(fraction) or not 0 <= fraction <= 1):
            raise ValueError("Invalid source sampling fraction")
    ids = [cell["body_id"] for cell in cells]
    positions = np.searchsorted(graph.ids, ids)
    if (len(set(ids)) != len(ids)
            or any(pos >= graph.size or int(graph.ids[pos]) != body
                   for pos, body in zip(positions, ids, strict=True))):
        raise ValueError("Source cells must be distinct registered graph neurons")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("Invalid seed")
    if (recording is not None and (not isinstance(recording, dict)
            or set(recording) != {"electrode_um", "reference_um", "source_model"}
            or not isinstance(recording["source_model"], str)
            or recording["source_model"] not in {"pointsource", "linesource"})):
        raise ValueError("Invalid recording configuration")
    if (acquisition is not None and (recording is None or not isinstance(acquisition, dict)
            or set(acquisition) != {"low_hz", "high_hz", "recovery_ms", "clip_uv"})):
        raise ValueError("Acquisition requires a recording and explicit settings")
    if (not isinstance(simulation_parameters, dict)
            or "synaptic_events" in simulation_parameters
            or type(simulation_parameters.get("nseg_per_edge", 1)) is not int
            or simulation_parameters.get("nseg_per_edge", 1) < 1
            or simulation_parameters.get("nseg_per_edge", 1) % 2 != 1):
        raise ValueError("Explicit source requires an odd segment count and no feedback")
    nseg = simulation_parameters.get("nseg_per_edge", 1)
    duration = simulation_parameters.get("duration_ms")
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or not float(duration).is_integer()
            or not 1 <= duration <= 1000):
        raise ValueError("Graph duration must be an integer number of milliseconds")
    duration = int(duration)
    sources, events = [], {}

    def simulate_sources():
        reference_time = None
        retained_events = 0
        for cell in cells:
            digest = cell.get("morphology_sha256")
            result, provenance = simulate_registered_swc_reference(
                cell["body_id"], directories,
                **({"expected_morphology_sha256": digest} if digest is not None else {}),
                **simulation_parameters,
            )
            if str(provenance.get("body_id")) != str(cell["body_id"]):
                raise ValueError("Source morphology identity mismatch")
            if digest is not None and provenance.get("morphology_sha256") != digest:
                raise ValueError("Source morphology digest mismatch")
            if (type(provenance.get("components")) is not int
                    or provenance["components"] != 1):
                raise ValueError("Source morphology must be one connected component "
                                 "for graph input")
            edge_ids = np.asarray(result["edge_node_ids"])
            locations = np.flatnonzero(edge_ids == cell["child_node_id"])
            if len(locations) != nseg or not np.array_equal(
                locations, np.arange(locations[0], locations[0] + nseg)
            ):
                raise ValueError("Selected source compartment is missing or ambiguous")
            time = np.asarray(result["time_ms"], dtype=float)
            voltage = np.asarray(result["voltage_mv"], dtype=float)
            if (voltage.ndim != 2 or voltage.shape != (len(edge_ids), len(time))
                    or not np.isfinite(voltage).all()):
                raise ValueError("Invalid source voltage dimensions or values")
            if reference_time is not None and not np.array_equal(reference_time, time):
                raise ValueError("Source-cell time grids differ")
            reference_time = time.copy()
            requested = cell.get("sampling_fraction")
            within_edge = nseg // 2 if requested is None else min(int(requested * nseg), nseg - 1)
            selected = int(locations[within_edge])
            trace = voltage[selected].copy()
            ticks = threshold_crossing_ticks(time, trace, threshold_mv=cell["threshold_mv"],
                                             duration_ms=duration)
            diagnostic = compartment_crossing_summary(
                time, voltage, selected_index=selected, threshold_mv=cell["threshold_mv"]
            )
            events[cell["body_id"]] = ticks.tolist()
            sampling = {"edge_fraction": (within_edge + .5) / nseg, "nseg_per_edge": nseg,
                        "result_segment_index": selected}
            if requested is not None:
                sampling["requested_edge_fraction"] = requested
            sources.append({"selection": dict(cell), "provenance": provenance,
                            "sampling": sampling,
                            "crossing_diagnostics": diagnostic,
                            "all_voltage_range_mv": {"minimum": float(np.min(voltage)),
                                                     "maximum": float(np.max(voltage))},
                            "time_ms": time.copy(), "voltage_mv": trace,
                            "event_ticks_ms": ticks})
            if retain_compartment_crossings:
                events_for_display = compartment_crossing_events(
                    time, voltage, result["midpoints_um"], threshold_mv=cell["threshold_mv"]
                )
                retained_events += len(events_for_display["sample_indices"])
                if retained_events > 1_000_000:
                    raise ValueError("Compartment crossing event limit exceeded")
                sources[-1]["compartment_crossings"] = events_for_display
            if solution_sink is not None:
                solution_sink(result, provenance)
            yield result, provenance

    if recording is None:
        for _ in simulate_sources():
            pass
        channel = None
    else:
        channel = record_independent_cells(
            simulate_sources(), recording["electrode_um"], recording["reference_um"],
            source_model=recording["source_model"],
        )
    network = run_forced_network(graph, seed=seed, duration_ms=duration,
                                 forced_cell_ids=ids, events=events)
    acquired = None if acquisition is None else acquire_independent_cells(channel, **acquisition)
    return {"sources": sources, "network": network, "recording": channel,
            "acquisition": acquired,
            "interpretation": "independent electrically stimulated source cells; "
                              "one-way event propagation into an uncalibrated LIF graph"}
