"""Compose experimental physical source cells and one-way downstream replay."""

from __future__ import annotations

import json

import numpy as np

from service.application.field.driven_network import run_field_driven_network
from service.application.replay.population_replay import replay_independent_population
from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.stimulation.acquisition import acquire_channel


def run_field_graph_replay(
    index,
    graph,
    directories,
    *,
    source_cells,
    replay_ids,
    simulation_parameters,
    schedule_parameters,
    recording,
    seed,
    acquisition=None,
    evidence_sink=None,
    provenance_sink=None,
    solution_sink=None,
    retain_compartment_crossings=False,
):
    """Combine disjoint source and replay cells; apply their shared artifact once.

    Downstream cells are reconstructed using a fixed saved network event stream;
    their membrane activity does not affect the network or source cells. Neither
    this hybrid nor its extracellular signal is a full biophysical network.
    """
    if (
        not isinstance(source_cells, list)
        or not source_cells
        or any(
            not isinstance(cell, dict) or type(cell.get("body_id")) is not int
            for cell in source_cells
        )
        or not isinstance(replay_ids, list)
        or not replay_ids
        or any(type(body) is not int or body <= 0 for body in replay_ids)
        or len(set(replay_ids)) != len(replay_ids)
    ):
        raise ValueError("Invalid source or replay cell selection")
    if {cell["body_id"] for cell in source_cells}.intersection(replay_ids):
        raise ValueError("Source and replay cell selections must not overlap")
    positions = np.searchsorted(graph.ids, replay_ids)
    if any(
        pos >= graph.size or int(graph.ids[pos]) != body
        for pos, body in zip(positions, replay_ids, strict=True)
    ):
        raise ValueError("Replay cell is not in the graph")
    if not isinstance(recording, dict) or set(recording) != {
        "electrode_um",
        "reference_um",
        "source_model",
    }:
        raise ValueError("An explicit differential recording configuration is required")
    if (
        not isinstance(schedule_parameters, dict)
        or not isinstance(simulation_parameters, dict)
        or schedule_parameters.get("duration_ms") != simulation_parameters.get("duration_ms")
    ):
        raise ValueError("Replay and source durations must match")
    if acquisition is not None and (
        not isinstance(acquisition, dict)
        or set(acquisition) != {"low_hz", "high_hz", "recovery_ms", "clip_uv"}
    ):
        raise ValueError("Invalid acquisition settings")
    if type(retain_compartment_crossings) is not bool:
        raise ValueError("Invalid compartment crossing retention setting")
    try:
        configuration = json.loads(
            json.dumps(
                {
                    "source_cells": source_cells,
                    "replay_ids": replay_ids,
                    "simulation_parameters": simulation_parameters,
                    "schedule_parameters": schedule_parameters,
                    "recording": recording,
                    "seed": seed,
                    "acquisition": acquisition,
                },
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Configuration must contain finite JSON values") from exc
    if retain_compartment_crossings:
        configuration["retain_compartment_crossings"] = True
    source = run_field_driven_network(
        graph,
        directories,
        cells=source_cells,
        simulation_parameters=simulation_parameters,
        seed=seed,
        recording=recording,
        solution_sink=solution_sink,
        retain_compartment_crossings=retain_compartment_crossings,
    )
    binary, description, digest = encode_forced_spikes(graph, source["network"])
    replay = replay_independent_population(
        index,
        graph,
        replay_ids,
        directories,
        binary=binary,
        description=description,
        expected_sha256=digest,
        schedule_parameters=schedule_parameters,
        simulation_parameters=simulation_parameters,
        electrode_um=recording["electrode_um"],
        reference_um=recording["reference_um"],
        source_model=recording["source_model"],
        evidence_sink=evidence_sink,
        provenance_sink=provenance_sink,
        solution_sink=solution_sink,
    )
    first = source["recording"]
    for field in ("time_ms", "stimulus_fraction", "stimulus_artifact_uv"):
        if not np.array_equal(first[field], replay[field]):
            raise ValueError("Source and replay recordings do not share the same stimulus and grid")
    for field in (
        "stimulation_parameters",
        "electrode_um",
        "reference_um",
        "coordinate_frame",
        "source_model",
    ):
        if first[field] != replay[field]:
            raise ValueError("Source and replay recording configurations differ")
    with np.errstate(over="ignore", invalid="ignore"):
        neural = first["neural_uv"] + replay["neural_uv"]
        total = neural + first["stimulus_artifact_uv"]
    if not np.isfinite(neural).all() or not np.isfinite(total).all():
        raise ValueError("Non-finite combined recording")
    combined = {
        "time_ms": first["time_ms"].copy(),
        "neural_uv": neural,
        "stimulus_artifact_uv": first["stimulus_artifact_uv"].copy(),
        "stimulus_fraction": first["stimulus_fraction"].copy(),
        "total_uv": total,
        "source_cells": first["cells"],
        "replay_cells": replay["cells"],
        "source_ordered_sha256": first["ordered_sources_sha256"],
        "replay_ordered_sha256": replay["ordered_sources_sha256"],
        "graph_stream_sha256": digest,
        "interpretation": "selected independent source and replay cells only",
    }
    acquired = (
        None
        if acquisition is None
        else acquire_channel(
            combined["time_ms"],
            combined["neural_uv"],
            combined["stimulus_artifact_uv"],
            combined["stimulus_fraction"],
            **acquisition,
        )
    )
    return {
        "source": source,
        "replay": replay,
        "recording": combined,
        "acquisition": acquired,
        "graph_description": description,
        "configuration": configuration,
        "interpretation": "one-way uncalibrated hybrid; no replay feedback or full-network "
        "physical recording",
    }
