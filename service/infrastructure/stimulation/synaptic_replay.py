"""Explicit one-way replay of network spikes at candidate SWC locations."""

from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np


def _read_verified_spike_arrays(binary, description, expected_sha256, graph_ids,
                                graph_manifest_sha256):
    """Verify and decode the graph-indexed spike arrays.

    The expected digest and graph manifest must come from the trusted run
    manifest; this function does not authenticate a caller-supplied manifest.
    """
    if (not isinstance(binary, bytes) or not isinstance(expected_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or hashlib.sha256(binary).hexdigest() != expected_sha256):
        raise ValueError("Connectome buffer checksum mismatch")
    if (not isinstance(description, dict)
            or description.get("manifest_sha256") != graph_manifest_sha256):
        raise ValueError("Connectome graph version mismatch")
    layout = description.get("binary")
    if (not isinstance(layout, dict) or layout.get("bytes") != len(binary)
            or layout.get("byte_order") != "little" or not isinstance(layout.get("arrays"), dict)):
        raise ValueError("Invalid connectome buffer layout")
    arrays, spans = {}, []
    for name, dtype in (("node_ids", "<u8"), ("spike_neurons", "<i4"), ("spike_times_ms", "<f4")):
        item = layout["arrays"].get(name)
        if (not isinstance(item, dict) or item.get("dtype") != dtype
                or type(item.get("offset")) is not int or type(item.get("count")) is not int
                or item["offset"] < 0 or item["count"] < 0 or item.get("shape") != [item["count"]]):
            raise ValueError("Invalid connectome array layout")
        end = item["offset"] + item["count"] * np.dtype(dtype).itemsize
        if end > len(binary):
            raise ValueError("Connectome array exceeds buffer")
        spans.append((item["offset"], end))
        arrays[name] = np.frombuffer(
            binary, dtype=dtype, count=item["count"], offset=item["offset"]
        )
    spans.sort()
    if any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1)):
        raise ValueError("Connectome arrays overlap")
    if not np.array_equal(arrays["node_ids"], graph_ids):
        raise ValueError("Connectome node IDs do not match graph")
    duration = description.get("duration_ms")
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or duration <= 0
            or np.any(arrays["spike_times_ms"] > duration)):
        raise ValueError("Spike times exceed saved recording duration")
    select_recorded_spikes(graph_ids, arrays["spike_neurons"], arrays["spike_times_ms"], [])
    return arrays["spike_neurons"], arrays["spike_times_ms"]


def read_verified_spikes(binary, description, expected_sha256, graph_ids, graph_manifest_sha256,
                         partner_ids):
    """Extract requested spike series from a verified saved connectome buffer."""
    indices, times = _read_verified_spike_arrays(
        binary, description, expected_sha256, graph_ids, graph_manifest_sha256
    )
    return select_recorded_spikes(graph_ids, indices, times, partner_ids)


def select_recorded_spikes(graph_ids, spike_indices, spike_times_ms, partner_ids):
    """Select spike times by source ID from the saved graph-indexed event stream.

    The caller must verify the graph and event-file identities before calling.
    """
    ids = np.asarray(graph_ids)
    indices = np.asarray(spike_indices)
    times = np.asarray(spike_times_ms)
    if (ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer)
            or len(ids) == 0 or np.any(ids <= 0) or np.any(ids[1:] <= ids[:-1])
            or indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer)
            or times.shape != indices.shape
            or not (np.issubdtype(times.dtype, np.floating)
                    or np.issubdtype(times.dtype, np.integer))
            or not np.isfinite(times).all() or np.any(times <= 0)
            or np.any(times[1:] < times[:-1])
            or np.any(indices < 0) or np.any(indices >= len(ids))):
        raise ValueError("Invalid graph-indexed spike stream")
    if (not isinstance(partner_ids, list)
            or any(type(value) is not int or value <= 0 for value in partner_ids)
            or len(set(partner_ids)) != len(partner_ids)):
        raise ValueError("Invalid replay partner IDs")
    if not partner_ids:
        return {}
    positions = np.searchsorted(ids, partner_ids)
    if any(pos >= len(ids) or int(ids[pos]) != body
           for pos, body in zip(positions, partner_ids, strict=True)):
        raise ValueError("Replay partner missing from graph")
    selected = np.isin(indices, positions)
    result = {str(body): [] for body in partner_ids}
    for index, time in zip(indices[selected], times[selected], strict=True):
        result[str(int(ids[index]))].append(float(time))
    return result


def schedule_candidate_events(mapping, spikes_by_body, *, delay_ms, duration_ms, weight_us,
                              tau1_ms, tau2_ms, reversal_mv, max_events=None,
                              partner_parameters=None):
    """Translate recorded presynaptic spikes into explicitly parameterized Exp2Syn events.

    The caller supplies a verified incoming mapping and all kinetic parameters.
    Optional per-partner parameters must cover every candidate; no transmitter
    effect is inferred from the graph or filled in silently.
    This is one-way replay, not a coupled network and not calibrated physiology.
    """
    values = (delay_ms, duration_ms, weight_us, tau1_ms, tau2_ms, reversal_mv)
    if (any(isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)
            for v in values) or delay_ms < 0 or duration_ms <= 0 or weight_us <= 0
            or not 0 < tau1_ms < tau2_ms or not 1e-9 <= tau1_ms / tau2_ms <= .9999
            or (max_events is not None and (type(max_events) is not int or max_events <= 0))):
        raise ValueError("Invalid replay parameters")
    if (not isinstance(mapping, dict) or mapping.get("direction") != "incoming"
            or not isinstance(mapping.get("candidates"), list)
            or not isinstance(spikes_by_body, dict)):
        raise ValueError("Replay requires incoming candidates and recorded spikes")
    parameter_keys = {"weight_us", "tau1_ms", "tau2_ms", "reversal_mv"}
    if partner_parameters is not None:
        if not isinstance(partner_parameters, dict):
            raise ValueError("Invalid per-partner parameters")
        for key, settings in partner_parameters.items():
            if (not isinstance(key, str) or not isinstance(settings, dict)
                    or set(settings) != parameter_keys):
                raise ValueError("Invalid per-partner parameters")
            local = [settings[name] for name in parameter_keys]
            if (any(isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)
                    for v in local) or settings["weight_us"] <= 0
                    or not 0 < settings["tau1_ms"] < settings["tau2_ms"]
                    or not 1e-9 <= settings["tau1_ms"] / settings["tau2_ms"] <= .9999):
                raise ValueError("Invalid per-partner parameters")
    for body, times in spikes_by_body.items():
        if (not isinstance(body, str) or not body.isascii() or not body.isdigit()
                or body.startswith("0") or not isinstance(times, list)
                or any(isinstance(t, bool) or not isinstance(t, int | float)
                       or not math.isfinite(t) or not 0 < t <= duration_ms for t in times)):
            raise ValueError("Invalid recorded spike series")
    events, event_sources = [], []
    outside_window = 0
    for candidate_index, candidate in enumerate(mapping["candidates"]):
        try:
            body = candidate["partner_id"]
            child = candidate["child_node_id"]
            position = candidate["segment_fraction"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Invalid candidate") from exc
        if (not isinstance(body, str) or not body.isascii() or not body.isdigit()
                or body.startswith("0") or type(child) is not int or child <= 0
                or isinstance(position, bool) or not isinstance(position, int | float)
                or not math.isfinite(position) or not 0 <= position <= 1):
            raise ValueError("Invalid candidate")
        if body not in spikes_by_body:
            raise ValueError("Missing recorded spike series for presynaptic partner")
        if partner_parameters is not None and body not in partner_parameters:
            raise ValueError("Missing synaptic parameters for presynaptic partner")
        params = (partner_parameters[body] if partner_parameters is not None else
                  {"weight_us": weight_us, "tau1_ms": tau1_ms, "tau2_ms": tau2_ms,
                   "reversal_mv": reversal_mv})
        for spike_index, spike in enumerate(spikes_by_body[body]):
            arrival = spike + delay_ms
            if arrival >= duration_ms:
                outside_window += 1
                continue
            if max_events is not None and len(events) >= max_events:
                raise ValueError("Replay exceeds the explicit event limit")
            events.append({"child_node_id": child, "position": position, "time_ms": arrival,
                           **params})
            event_sources.append({"candidate_index": candidate_index, "presynaptic_id": body,
                                  "spike_index": spike_index, "spike_time_ms": spike})
    return {"events": events, "event_sources": event_sources, "outside_window": outside_window,
            "interpretation": "one-way replay; candidate locations and parameters uncalibrated"}


def execute_reference_replay(mapping, spikes_by_body, directories, *, schedule_parameters,
                             simulation_parameters, electrode_um, reference_um,
                             source_model="pointsource"):
    """Execute a candidate-page replay on its verified SWC and record E1–REF.

    Mapping must originate from registered_page_candidates. This procedure is
    an isolated, one-way replay and does not feed membrane activity into LIF.
    """
    from service.infrastructure.connectome.morphology_repository import read_skeleton
    from service.infrastructure.stimulation.swc_reference import (
        record_swc_with_stimulus_artifact,
        simulate_registered_swc_reference,
    )

    body = mapping.get("body_id") if isinstance(mapping, dict) else None
    if (not isinstance(body, str) or not body.isascii() or not body.isdigit()
            or body.startswith("0") or int(body) >= 2**63):
        raise ValueError("Invalid replay target")
    if (not isinstance(simulation_parameters, dict) or "synaptic_events" in simulation_parameters
            or not isinstance(schedule_parameters, dict)
            or schedule_parameters.get("duration_ms") != simulation_parameters.get("duration_ms")):
        raise ValueError("Replay durations or simulation parameters do not match")
    skeleton = read_skeleton(int(body), directories)
    if skeleton["sha256"] != mapping.get("morphology_sha256"):
        raise ValueError("Replay mapping and target morphology differ")
    replay = schedule_candidate_events(mapping, spikes_by_body, **schedule_parameters)
    solution, provenance = simulate_registered_swc_reference(
        int(body), directories, **simulation_parameters, synaptic_events=replay["events"]
    )
    if provenance["morphology_sha256"] != skeleton["sha256"]:
        raise ValueError("Target morphology changed during replay")
    channel = record_swc_with_stimulus_artifact(
        solution, provenance, electrode_um, reference_um, source_model=source_model
    )
    return {"solution": solution, "provenance": provenance, "replay": replay,
            "channel": channel, "recording_source_model": source_model,
            "recording_configuration": {
                "electrode_um": np.asarray(electrode_um, dtype=float).tolist(),
                "reference_um": np.asarray(reference_um, dtype=float).tolist(),
                "coordinate_frame": "MaleCNS native EM, micrometres",
                "conductivity_s_m": provenance["configuration"]["conductivity_s_m"],
                "source_model": source_model,
                "signal_units": "microvolts",
                "medium": "infinite homogeneous isotropic conductor",
            }}


def execute_registered_replay(index, graph, body_id, offset, limit, directories, *, binary,
                              description, expected_sha256, schedule_parameters,
                              simulation_parameters, electrode_um, reference_um,
                              source_model="pointsource"):
    """Verify one incoming graph page and replay saved spikes on its target SWC.

    The expected checksum must come from an authenticated run manifest. The
    result covers only one page and is a one-way, uncalibrated reconstruction.
    """
    from service.infrastructure.connectome.synapse_morphology import registered_page_candidates

    mapping = registered_page_candidates(
        index, graph, body_id, "incoming", offset, limit, directories
    )
    return _execute_mapping_replay(mapping, graph, directories, binary=binary,
                                   description=description, expected_sha256=expected_sha256,
                                   schedule_parameters=schedule_parameters,
                                   simulation_parameters=simulation_parameters,
                                   electrode_um=electrode_um, reference_um=reference_um,
                                   source_model=source_model)


def _execute_mapping_replay(mapping, graph, directories, *, binary, description, expected_sha256,
                            schedule_parameters, simulation_parameters, electrode_um,
                            reference_um, source_model, preselected_spikes=None):
    partners = sorted({int(candidate["partner_id"]) for candidate in mapping["candidates"]})
    spikes = (read_verified_spikes(binary, description, expected_sha256, graph.ids,
                                   graph.provenance["manifest_sha256"], partners)
              if preselected_spikes is None else preselected_spikes(partners))
    duration = schedule_parameters.get("duration_ms")
    source_duration = description.get("duration_ms")
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or duration <= 0
            or isinstance(source_duration, bool) or not isinstance(source_duration, int | float)
            or not math.isfinite(source_duration) or duration > source_duration):
        raise ValueError("Replay duration exceeds the saved network recording")
    omitted = sum(time > duration for times in spikes.values() for time in times)
    bounded_spikes = {key: [time for time in times if time <= duration]
                      for key, times in spikes.items()}
    result = execute_reference_replay(
        mapping, bounded_spikes, directories, schedule_parameters=schedule_parameters,
        simulation_parameters=simulation_parameters, electrode_um=electrode_um,
        reference_um=reference_um, source_model=source_model,
    )
    return {**result, "mapping": mapping, "selected_spikes": bounded_spikes,
            "spikes_after_replay_window": omitted, "connectome_sha256": expected_sha256,
            "interpretation": "one-way replay, not a coupled or calibrated network"}


def execute_all_incoming_replay(
    index, graph, body_id, directories, *, binary, description, expected_sha256,
    schedule_parameters, simulation_parameters, electrode_um, reference_um,
    source_model="pointsource", progress=None,
):
    """Replay all checked incoming graph pages without implicit partial coverage.

    This is still an independent-cell model with explicit uncalibrated synaptic
    parameters. Callers must provide a checksum from a trusted run manifest.
    """
    from service.infrastructure.connectome.synapse_morphology import (
        registered_incoming_candidates_single_pass,
    )

    indices, times = _read_verified_spike_arrays(
        binary, description, expected_sha256, graph.ids, graph.provenance["manifest_sha256"]
    )
    duration, delay = schedule_parameters.get("duration_ms"), schedule_parameters.get("delay_ms")
    if (isinstance(duration, bool) or not isinstance(duration, int | float)
            or not math.isfinite(duration) or duration <= 0
            or isinstance(delay, bool) or not isinstance(delay, int | float)
            or not math.isfinite(delay) or delay < 0
            or duration > description["duration_ms"]):
        raise ValueError("Invalid replay time window")
    active = {int(graph.ids[index]) for index in indices[times.astype(float) + delay < duration]}
    mapping = registered_incoming_candidates_single_pass(
        index, graph, body_id, directories, candidate_partner_ids=active, progress=progress,
    )
    return _execute_mapping_replay(mapping, graph, directories, binary=binary,
                                   description=description, expected_sha256=expected_sha256,
                                   schedule_parameters=schedule_parameters,
                                   simulation_parameters=simulation_parameters,
                                   electrode_um=electrode_um, reference_um=reference_um,
                                   source_model=source_model)


def _execute_preverified_incoming_replay(
    index, graph, body_id, directories, *, binary, description, expected_sha256,
    schedule_parameters, simulation_parameters, electrode_um, reference_um,
    source_model, spike_index, active,
):
    """Internal population path: spike stream and time window verified once."""
    from service.infrastructure.connectome.synapse_morphology import (
        registered_incoming_candidates_single_pass,
    )

    mapping = registered_incoming_candidates_single_pass(
        index, graph, body_id, directories, candidate_partner_ids=active,
    )
    return _execute_mapping_replay(mapping, graph, directories, binary=binary,
                                   description=description, expected_sha256=expected_sha256,
                                   schedule_parameters=schedule_parameters,
                                   simulation_parameters=simulation_parameters,
                                   electrode_um=electrode_um, reference_um=reference_um,
                                   source_model=source_model, preselected_spikes=spike_index.select)


def replay_evidence_json(result):
    """Serialize source mappings, spikes, events and model settings canonically.

    Caller stores these bytes with the waveform and their digests; large state
    arrays are deliberately not embedded into the evidence document.
    """
    keys = ("mapping", "selected_spikes", "spikes_after_replay_window", "connectome_sha256",
            "provenance", "replay", "recording_configuration", "interpretation")
    if not isinstance(result, dict) or any(key not in result for key in keys):
        raise ValueError("Incomplete replay evidence")
    evidence = {"format": "independent-swc-replay-evidence-v1",
                **{key: result[key] for key in keys}}
    if "request" in result:
        evidence["request"] = result["request"]
    try:
        return (json.dumps(evidence, sort_keys=True, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Replay evidence must be finite JSON") from exc
