"""Stream a sum of independently replayed registered neurons.

This is not a coupled compartmental network, a calibrated electrode model, or
an anatomical registration of the visible body. All source events remain those
of the saved LIF network and cannot be modified by the replayed cells.
"""

from __future__ import annotations

import hashlib

import numpy as np

from service.infrastructure.stimulation.network_recording import record_independent_cells
from service.infrastructure.stimulation.synaptic_replay import (
    _execute_preverified_incoming_replay,
    replay_evidence_json,
)
from service.infrastructure.stimulation.verified_spike_index import VerifiedSpikeIndex


def replay_independent_population(
    index, graph, body_ids, directories, *, binary, description, expected_sha256,
    schedule_parameters, simulation_parameters, electrode_um, reference_um,
    source_model="pointsource", evidence_sink=None, provenance_sink=None, solution_sink=None,
):
    """Replay cells sequentially and sum their physical channels on a common grid.

    Evidence is canonical JSONL in requested order. Each line retains the
    source mapping, events and solver parameters. Output is not published here;
    callers must discard partial files when a cell or write fails.
    """
    if not isinstance(body_ids, (list, tuple)) or not body_ids:
        raise ValueError("Population must contain registered neuron IDs")
    if (any(type(value) is not int or value <= 0 for value in body_ids)
            or len(set(body_ids)) != len(body_ids)):
        raise ValueError("Population IDs must be unique positive integers")
    indices = np.searchsorted(graph.ids, body_ids)
    if any(index >= len(graph.ids) or int(graph.ids[index]) != body_id
           for index, body_id in zip(indices, body_ids, strict=True)):
        raise ValueError("Population contains an unregistered neuron")
    spike_index = VerifiedSpikeIndex(binary, description, expected_sha256, graph.ids,
                                     graph.provenance["manifest_sha256"])
    active = spike_index.active_before(schedule_parameters.get("duration_ms"),
                                       schedule_parameters.get("delay_ms"))
    evidence_hash = hashlib.sha256()
    complete = True
    voltage_minimum, voltage_maximum = float("inf"), float("-inf")

    def records():
        nonlocal complete, voltage_minimum, voltage_maximum
        for body_id in body_ids:
            result = _execute_preverified_incoming_replay(
                index, graph, body_id, directories, binary=binary, description=description,
                expected_sha256=expected_sha256, schedule_parameters=schedule_parameters,
                simulation_parameters=simulation_parameters, electrode_um=electrode_um,
                reference_um=reference_um, source_model=source_model,
                spike_index=spike_index, active=active,
            )
            if result["mapping"]["body_id"] != str(body_id):
                raise ValueError("Replay returned the wrong neuron")
            voltage = np.asarray(result["solution"]["voltage_mv"], dtype=float)
            if voltage.ndim != 2 or not voltage.size or not np.isfinite(voltage).all():
                raise ValueError("Invalid replay-cell voltage dimensions or values")
            voltage_minimum = min(voltage_minimum, float(np.min(voltage)))
            voltage_maximum = max(voltage_maximum, float(np.max(voltage)))
            complete &= result["mapping"].get("complete_graph_edge_coverage") is True
            evidence = replay_evidence_json(result)
            evidence_hash.update(evidence)
            if evidence_sink is not None and evidence_sink.write(evidence) != len(evidence):
                raise OSError("Incomplete replay evidence write")
            if solution_sink is not None:
                solution_sink(result["solution"], result["provenance"])
            yield result["solution"], result["provenance"]

    recording = record_independent_cells(
        records(), electrode_um, reference_um, source_model=source_model,
        provenance_sink=provenance_sink,
    )
    return {**recording, "source_sha256": expected_sha256,
            "all_voltage_range_mv": {"minimum": voltage_minimum, "maximum": voltage_maximum},
            "graph_manifest_sha256": graph.provenance["manifest_sha256"],
            "replay_evidence_sha256": evidence_hash.hexdigest(),
            "replay_evidence_exported": evidence_sink is not None,
            "complete_incoming_graph_coverage": complete,
            "interpretation": "sum of independent one-way replays; not a coupled or "
                              "calibrated network"}
