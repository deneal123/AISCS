"""Paired local output diagnostics for independently simulated SWC fragments.

Results are not neuronal spike schedules. A separate experimental adapter can
map resolved local events to registered graph edges without inferring any
connection between reconstructed components.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter

import numpy as np

from service.infrastructure.connectome.forced_network import (
    threshold_crossing_intervals,
    validate_crossing_intervals,
)
from service.infrastructure.connectome.fragment_mapping import (
    fragment_roots,
    map_fragment_candidates,
)
from service.infrastructure.connectome.morphology_repository import read_skeleton
from service.infrastructure.connectome.neighbors import outgoing


def fragment_output_diagnostics(
    swc,
    points_um,
    stimulated,
    control,
    provenance,
    control_provenance,
    *,
    threshold_mv,
    duration_ms,
):
    """Compare stimulus and control at nearest cable candidates, retaining uncertainty."""
    if (
        not isinstance(swc, str)
        or not isinstance(provenance, dict)
        or not isinstance(control_provenance, dict)
    ):
        raise ValueError("Invalid morphology provenance")
    if provenance.get("morphology_sha256") != hashlib.sha256(swc.encode("utf8")).hexdigest():
        raise ValueError("Morphology digest mismatch")
    body = provenance.get("body_id")
    if (
        not isinstance(body, str)
        or not body.isascii()
        or not body.isdigit()
        or body.startswith("0")
        or int(body) >= 2**63
    ):
        raise ValueError("Invalid morphology identity")
    if body != control_provenance.get("body_id") or provenance.get(
        "morphology_sha256"
    ) != control_provenance.get("morphology_sha256"):
        raise ValueError("Paired morphology provenance mismatch")
    active_config = provenance.get("configuration")
    quiet_config = control_provenance.get("configuration")
    if (
        not isinstance(active_config, dict)
        or not isinstance(quiet_config, dict)
        or any(key not in active_config or key not in quiet_config for key in ("current_na",))
        or isinstance(active_config["current_na"], bool)
        or not isinstance(active_config["current_na"], int | float)
        or not math.isfinite(active_config["current_na"])
        or isinstance(quiet_config["current_na"], bool)
        or quiet_config["current_na"] != 0
        or any(
            type(config.get("record_membrane_current", True)) is not bool
            for config in (active_config, quiet_config)
        )
        or {
            k: v
            for k, v in active_config.items()
            if k not in {"current_na", "record_membrane_current"}
        }
        != {
            k: v
            for k, v in quiet_config.items()
            if k not in {"current_na", "record_membrane_current"}
        }
    ):
        raise ValueError("Paired stimulation configurations mismatch")
    roots = fragment_roots(swc)
    if (
        type(provenance.get("components")) is not int
        or provenance["components"] != len(set(roots.values()))
        or type(control_provenance.get("components")) is not int
        or control_provenance.get("components") != provenance["components"]
    ):
        raise ValueError("Morphology component count mismatch")
    if (
        isinstance(threshold_mv, bool)
        or not isinstance(threshold_mv, int | float)
        or not math.isfinite(threshold_mv)
        or type(duration_ms) is not int
        or duration_ms < 1
        or active_config.get("duration_ms") != duration_ms
    ):
        raise ValueError("Invalid threshold or duration")
    if not isinstance(stimulated, dict) or not isinstance(control, dict):
        raise ValueError("Invalid solutions")
    time = np.asarray(stimulated.get("time_ms"), dtype=float)
    second_time = np.asarray(control.get("time_ms"), dtype=float)
    ids = np.asarray(stimulated.get("edge_node_ids"))
    control_ids = np.asarray(control.get("edge_node_ids"))
    active = np.asarray(stimulated.get("voltage_mv"), dtype=float)
    quiet = np.asarray(control.get("voltage_mv"), dtype=float)
    if (
        time.ndim != 1
        or len(time) < 2
        or not np.array_equal(time, second_time)
        or ids.ndim != 1
        or ids.dtype.kind not in "iu"
        or not np.array_equal(ids, control_ids)
        or active.shape != (len(ids), len(time))
        or quiet.shape != active.shape
        or not np.isfinite(active).all()
        or not np.isfinite(quiet).all()
    ):
        raise ValueError("Paired solutions do not match")
    if active_config["current_na"] == 0 and not np.array_equal(active, quiet):
        raise ValueError("Zero-current paired solutions differ")
    nseg = provenance.get("configuration", {}).get("nseg_per_edge")
    if type(nseg) is not int or nseg < 1 or nseg % 2 != 1:
        raise ValueError("Missing or invalid segment count")
    overrides = active_config.get('nseg_by_edge', {})
    if (not isinstance(overrides, dict) or any(
            type(key) is not str or not key.isascii() or not key.isdigit()
            or str(int(key)) != key or int(key) <= 0 or int(key) not in ids
            or type(value) is not int or value < 1 or value % 2 != 1
            for key, value in overrides.items())):
        raise ValueError('Invalid per-edge segment counts')
    mapping = map_fragment_candidates(swc, points_um)
    diagnostics = []
    for child, fraction, root, distance in zip(
        mapping["child_node_ids"],
        mapping["segment_fractions"],
        mapping["component_root_ids"],
        mapping["centerline_distances_um"],
        strict=True,
    ):
        edge_nseg = overrides.get(str(child), nseg)
        matches = np.flatnonzero(ids == child)
        if len(matches) != edge_nseg or not np.array_equal(
            matches, np.arange(matches[0], matches[0] + edge_nseg)
        ):
            raise ValueError("Candidate segment missing or ambiguous")
        selected = int(matches[min(int(fraction * edge_nseg), edge_nseg - 1)])
        try:
            active_intervals = threshold_crossing_intervals(
                time, active[selected], threshold_mv=threshold_mv, duration_ms=duration_ms
            )
            control_intervals = threshold_crossing_intervals(
                time, quiet[selected], threshold_mv=threshold_mv, duration_ms=duration_ms
            )
            active_ticks = [item['tick_ms'] for item in active_intervals]
            control_ticks = [item['tick_ms'] for item in control_intervals]
            status = (
                "control_crossing"
                if control_ticks
                else "stimulus_only_crossing"
                if active_ticks
                else "no_crossing"
            )
        except ValueError:
            active_ticks, control_ticks, status = None, None, "timing_or_trace_ambiguous"
            active_intervals, control_intervals = None, None
        diagnostics.append(
            {
                "child_node_id": child,
                "segment_fraction": float(fraction),
                "component_root_id": root,
                "centerline_distance_um": distance,
                "result_segment_index": selected,
                "max_stimulated_mv": float(np.max(active[selected])),
                "max_control_mv": float(np.max(quiet[selected])),
                "max_abs_delta_mv": float(np.max(np.abs(active[selected] - quiet[selected]))),
                "status": status,
                "stimulated_ticks_ms": active_ticks,
                "control_ticks_ms": control_ticks,
                "stimulated_crossing_intervals": active_intervals,
                "control_crossing_intervals": control_intervals,
            }
        )
    return {
        "components": provenance["components"],
        "duration_ms": duration_ms,
        "threshold_mv": float(threshold_mv),
        "simulation_sha256": hashlib.sha256(
            json.dumps(
                active_config, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf8")
        ).hexdigest(),
        "candidates": diagnostics,
        "interpretation": (
            "local paired threshold diagnostics on nearest reconstructed cable; "
            "no fragment connectivity or graph spike schedule inferred"
        ),
    }


def _registered_source_coordinates(index, graph, body_id, directories, expected_sha256=None):
    """Read all registered outgoing coordinates and verify their graph counts."""
    if index.manifest.get("ids_sha256") != graph.provenance["array_sha256"]["ids.npy"]:
        raise ValueError("Synapse index and graph neuron IDs differ")
    source = read_skeleton(body_id, directories, expected_sha256=expected_sha256)
    page = index.query(body_id, "outgoing", limit=None)
    if (
        page["truncated"]
        or page["returned"] != page["total"]
        or len(page["pairs"]) != page["total"]
    ):
        raise ValueError("Incomplete source synapse scan")
    edges = outgoing(graph, body_id, 0, len(graph.posts))
    if edges["next_offset"] is not None:
        raise ValueError("Incomplete graph edge scan")
    expected = {int(row["target_id"]): row["synapse_count"] for row in edges["items"]}
    counts = Counter(row["body_post"] for row in page["pairs"] if row["body_post"] in expected)
    if any(counts[partner] != amount for partner, amount in expected.items()):
        raise ValueError("Synapse counts do not match the registered graph")
    if not page["pairs"]:
        raise ValueError("No outgoing synapse coordinates available")
    points = [[row[f"{axis}_pre"] * 0.008 for axis in "xyz"] for row in page["pairs"]]
    return source, page, expected, points


def preflight_outgoing_fragment_geometry(index, graph, body_id, directories, *, max_distance_um,
                                         allow_partial_geometry=False):
    """Check registered synapses before solving; strict unless explicitly partial."""
    if (isinstance(max_distance_um, bool) or not isinstance(max_distance_um, int | float)
            or not math.isfinite(max_distance_um) or max_distance_um < 0
            or type(allow_partial_geometry) is not bool):
        raise ValueError("Invalid geometric tolerance")
    source, page, expected, points = _registered_source_coordinates(
        index, graph, body_id, directories
    )
    graph_points = [point for point, pair in zip(points, page["pairs"], strict=True)
                    if pair["body_post"] in expected]
    if not graph_points:
        receipt = {"body_id": body_id, "graph_pairs": 0, "morphology_sha256": source["sha256"]}
        if allow_partial_geometry:
            receipt.update({"unresolved_graph_pairs": 0, "geometry_complete": True})
        return receipt
    mapped = map_fragment_candidates(source["swc"], graph_points)
    distances = mapped["centerline_distances_um"]
    if len(distances) != len(graph_points) or any(
        isinstance(value, bool) or not isinstance(value, int | float)
        or not math.isfinite(value) or value < 0 for value in distances
    ):
        raise ValueError("Unresolved geometric candidate: invalid distance")
    outside = [value for value in distances if value > max_distance_um]
    if outside and not allow_partial_geometry:
        raise ValueError(
            f"Unresolved geometric candidate: source {body_id}, "
            f"{len(outside)}/{len(distances)} graph synapses outside {max_distance_um:g} um; "
            f"maximum {max(outside):.6g} um"
        )
    receipt = {"body_id": body_id, "graph_pairs": len(distances),
               "morphology_sha256": source["sha256"]}
    if allow_partial_geometry:
        receipt.update({"unresolved_graph_pairs": len(outside), "geometry_complete": not outside})
    return receipt


def registered_outgoing_fragment_diagnostics(
    index, graph, body_id, directories, stimulated, control, provenance, control_provenance,
    *, threshold_mv, duration_ms,
):
    """Check every source coordinate against the registered outgoing graph."""
    if str(body_id) != provenance.get("body_id"):
        raise ValueError("Source and simulated neuron differ")
    source, page, expected, points = _registered_source_coordinates(
        index, graph, body_id, directories, provenance.get("morphology_sha256")
    )
    result = fragment_output_diagnostics(
        source["swc"],
        points,
        stimulated,
        control,
        provenance,
        control_provenance,
        threshold_mv=threshold_mv,
        duration_ms=duration_ms,
    )
    candidates = [
        {
            **diagnostic,
            "partner_id": str(pair["body_post"]),
            "included_in_graph": pair["body_post"] in expected,
            "source_position_8nm": [pair[f"{axis}_pre"] for axis in "xyz"],
        }
        for diagnostic, pair in zip(result["candidates"], page["pairs"], strict=True)
    ]
    return {
        **result,
        "body_id": str(body_id),
        "morphology_sha256": source["sha256"],
        "source_md5": page["source_md5"],
        "graph_sha256": graph.provenance["manifest_sha256"],
        "graph_edges": len(expected),
        "source_pairs": len(candidates),
        "graph_pairs": sum(row["included_in_graph"] for row in candidates),
        "candidates": candidates,
    }


def fragment_edge_schedule(diagnostics, *, max_distance_um, duration_ms,
                           allow_partial_geometry=False, include_control_crossings=False):
    """Summarize local graph-pair events; this remains an unvalidated hypothesis.

    By default every graph pair must be within the explicit cutoff. With
    explicit partial geometry, unresolved pairs are returned separately and
    never treated as negative observations. Non-graph pairs remain outside
    the schedule.
    """
    if (
        type(include_control_crossings) is not bool
        or not isinstance(diagnostics, dict)
        or not isinstance(diagnostics.get("candidates"), list)
        or type(duration_ms) is not int
        or duration_ms < 1
        or diagnostics.get("duration_ms") != duration_ms
        or isinstance(max_distance_um, bool)
        or not isinstance(max_distance_um, int | float)
        or not math.isfinite(max_distance_um)
        or max_distance_um < 0
        or type(allow_partial_geometry) is not bool
    ):
        raise ValueError("Invalid fragment schedule request")
    if not isinstance(diagnostics.get("graph_sha256"), str) or not re.fullmatch(
        r"[a-f0-9]{64}", diagnostics["graph_sha256"]
    ):
        raise ValueError("Missing graph identity")
    if not isinstance(diagnostics.get("simulation_sha256"), str) or not re.fullmatch(
        r"[a-f0-9]{64}", diagnostics["simulation_sha256"]
    ):
        raise ValueError("Missing simulation identity")
    threshold = diagnostics.get("threshold_mv")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int | float)
        or not math.isfinite(threshold)
    ):
        raise ValueError("Missing threshold identity")
    body = diagnostics.get("body_id")
    if (
        not isinstance(body, str)
        or not body.isascii()
        or not body.isdigit()
        or body.startswith("0")
        or int(body) >= 2**63
    ):
        raise ValueError("Invalid fragment source")
    rows = diagnostics["candidates"]
    if (
        type(diagnostics.get("source_pairs")) is not int
        or diagnostics["source_pairs"] != len(rows)
        or type(diagnostics.get("graph_pairs")) is not int
        or diagnostics["graph_pairs"]
        != sum(row.get("included_in_graph") is True for row in rows if isinstance(row, dict))
    ):
        raise ValueError("Incomplete fragment candidate coverage")
    distances = [
        row.get("centerline_distance_um")
        for row in rows
        if isinstance(row, dict) and row.get("included_in_graph") is True
    ]
    if any(
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
        for value in distances
    ):
        raise ValueError("Unresolved geometric candidate: invalid distance")
    outside = [value for value in distances if value > max_distance_um]
    if outside and not allow_partial_geometry:
        raise ValueError(
            f"Unresolved geometric candidate: source {body}, "
            f"{len(outside)}/{len(distances)} graph synapses "
            f"outside {max_distance_um:g} um; maximum {max(outside):.6g} um"
        )
    events = Counter()
    unresolved = []
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or type(row.get("included_in_graph")) is not bool:
            raise ValueError("Invalid fragment candidate")
        if not row["included_in_graph"]:
            continue
        distance, partner, status = (
            row.get("centerline_distance_um"),
            row.get("partner_id"),
            row.get("status"),
        )
        if (
            isinstance(distance, bool)
            or not isinstance(distance, int | float)
            or not math.isfinite(distance)
            or distance < 0
        ):
            raise ValueError("Unresolved geometric candidate")
        if (
            not isinstance(partner, str)
            or not partner.isascii()
            or not partner.isdigit()
            or partner.startswith("0")
            or int(partner) >= 2**63
        ):
            raise ValueError("Invalid fragment partner")
        if distance > max_distance_um:
            # Preserve the identity of the omitted measured connection. The
            # nearest fragment's simulated voltage is not its observed state.
            if (row.get('status') != 'geometry_unresolved'
                    or row.get('stimulated_ticks_ms') is not None
                    or row.get('control_ticks_ms') is not None
                    or any(row.get(key) is not None for key in (
                        'stimulated_crossing_intervals', 'control_crossing_intervals',
                        'max_stimulated_mv', 'max_control_mv', 'max_abs_delta_mv'))):
                raise ValueError('Unresolved source geometry cannot have observed events')
            entry = {"candidate_index": row_index, "partner_id": partner,
                     "centerline_distance_um": distance}
            point = row.get("source_position_8nm")
            if (not isinstance(point, list) or len(point) != 3
                    or any(type(value) is not int or value < 0 for value in point)):
                raise ValueError("Invalid unresolved synapse coordinates")
            entry["source_position_8nm"] = point
            unresolved.append(entry)
            continue
        ticks, control = row.get("stimulated_ticks_ms"), row.get("control_ticks_ms")
        if (
            status not in {"no_crossing", "stimulus_only_crossing", "control_crossing"}
            or (not include_control_crossings and control != [])
            or not isinstance(control, list)
            or any(type(tick) is not int or not 1 <= tick <= duration_ms for tick in control)
            or any(a >= b for a, b in zip(control, control[1:], strict=False))
            or not isinstance(ticks, list)
            or any(type(tick) is not int or not 1 <= tick <= duration_ms for tick in ticks)
            or any(a >= b for a, b in zip(ticks, ticks[1:], strict=False))
            or (status == 'control_crossing') != bool(control)
            or (not control and bool(ticks) != (status == "stimulus_only_crossing"))
        ):
            raise ValueError("Unresolved local threshold result")
        interval_keys = {'stimulated_crossing_intervals', 'control_crossing_intervals'}
        if interval_keys.intersection(row):
            if not interval_keys.issubset(row):
                raise ValueError('Incomplete crossing intervals')
            validate_crossing_intervals(row['stimulated_crossing_intervals'], ticks,
                                        duration_ms=duration_ms)
            validate_crossing_intervals(row['control_crossing_intervals'], control,
                                        duration_ms=duration_ms)
        for tick in ticks:
            events[(int(body), int(partner), tick)] += 1
    result = {
        "source_id": int(body),
        "graph_sha256": diagnostics.get("graph_sha256"),
        "simulation_sha256": diagnostics["simulation_sha256"],
        "threshold_mv": threshold,
        "max_distance_um": max_distance_um,
        "source_pairs": len(rows),
        "graph_pairs": diagnostics["graph_pairs"],
        "edge_events": [
            {"source_id": source, "target_id": target, "tick": tick, "count": count}
            for (source, target, tick), count in sorted(events.items())
        ],
        "interpretation": "experimental local edge schedule; not validated neuronal spikes",
    }
    if allow_partial_geometry:
        result["unresolved_geometry"] = unresolved
        result["resolved_graph_pairs"] = diagnostics["graph_pairs"] - len(unresolved)
        result["geometry_complete"] = not unresolved
    return result
