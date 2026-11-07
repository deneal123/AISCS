"""Conservative bounded preview of an experimentally verified hybrid recording."""

from __future__ import annotations

import hashlib
import json

import numpy as np

from service.infrastructure.stimulation.field_graph_export import load_verified_field_graph_replay
from service.infrastructure.stimulation.synaptic_replay import _read_verified_spike_arrays


def field_graph_preview(directory, graph, *, bins=512):
    """Retain extrema and mark each output sample invalid if its bin is invalid."""
    if type(bins) is not int or bins <= 0:
        raise ValueError("Preview bins must be a positive integer")
    verified = load_verified_field_graph_replay(directory, graph)
    arrays, metadata = verified["arrays"], verified["metadata"]
    _, spike_times = _read_verified_spike_arrays(
        verified["graph_binary"], metadata["graph_description"], metadata["graph_sha256"],
        graph.ids, graph.provenance["manifest_sha256"],
    )
    if np.any(spike_times != np.rint(spike_times)):
        raise ValueError("Graph event times must use whole-millisecond ticks")
    duration = metadata["graph_description"]["duration_ms"]
    counts = np.bincount(spike_times.astype(int), minlength=duration + 1)
    time = arrays["time_ms"]
    # Stimulus extrema must survive decimation even if the electrode artifact
    # and neural response are zero or do not peak at the stimulus times.
    signals = [arrays["neural_uv"], arrays["total_uv"], arrays["stimulus_fraction"]]
    has_acquisition = metadata["acquisition_settings"] is not None
    if has_acquisition:
        signals.append(arrays["filtered_total_uv"])
    valid = arrays["valid_samples"] if has_acquisition else None
    saturated = arrays["saturated_samples"] if has_acquisition else None
    # Preserve boundaries and slope changes in the sampled stimulus. Otherwise
    # interpolation after decimation can invent an early ramp or shorten a
    # plateau even when its extrema and zero/nonzero boundaries survive.
    stimulus = arrays["stimulus_fraction"]
    active = np.abs(stimulus) > 1e-9
    transition = np.flatnonzero(active[1:] != active[:-1])
    slopes = np.diff(stimulus) / np.diff(time)
    changes = np.flatnonzero(~np.isclose(slopes[1:], slopes[:-1], rtol=1e-6, atol=1e-9)) + 1
    protected = np.unique(np.concatenate((transition, transition + 1, changes)))
    # Pathological high-frequency input still has a bounded preview. The
    # ordinary two-phase pulse uses at most eight protected samples.
    preserve_boundaries = len(protected) <= 2048
    if not preserve_boundaries:
        protected = np.empty(0, dtype=int)
    # Up to ten extrema/endpoints per bin, plus protected boundary samples.
    max_bins = (4096 - len(protected)) // 10
    edges = np.linspace(0, len(time), min(bins, len(time), max_bins) + 1, dtype=int)
    selected, bins_valid, bins_saturated = {}, {}, {}
    intervals = []
    for start, end in zip(edges[:-1], edges[1:], strict=True):
        candidates = {start, end - 1}
        for signal in signals:
            candidates.add(start + int(np.argmin(signal[start:end])))
            candidates.add(start + int(np.argmax(signal[start:end])))
        left, right = np.searchsorted(protected, (start, end))
        candidates.update(int(index) for index in protected[left:right])
        if has_acquisition:
            intervals.append({"start_ms": float(time[0] if start == 0 else
                                                (time[start - 1] + time[start]) / 2),
                              "end_ms": float(time[-1] if end == len(time) else
                                              (time[end - 1] + time[end]) / 2),
                              "valid": bool(np.all(valid[start:end])),
                              "saturated": bool(np.any(saturated[start:end]))})
        for index in candidates:
            selected[index] = None
            if has_acquisition:
                bins_valid[index] = bool(np.all(valid[start:end]))
                bins_saturated[index] = bool(np.any(saturated[start:end]))
    indices = np.asarray(sorted(selected), dtype=int)
    output = {
        "time_ms": time[indices].tolist(),
        "neural_uv": arrays["neural_uv"][indices].tolist(),
        "total_uv": arrays["total_uv"][indices].tolist(),
        "stimulus_fraction": arrays["stimulus_fraction"][indices].tolist(),
        "samples": len(time),
        "shown_samples": len(indices),
        "selection": ("per-bin endpoints, signal extrema and stimulus slope changes"
                      if preserve_boundaries else "per-bin endpoints and signal extrema"),
        "source_cells": len(metadata["source_cells"]),
        "replay_cells": len(metadata["configuration"]["replay_ids"]),
        "network_spikes_by_ms": counts.tolist(),
        "limitations": [
            "Only selected independently simulated cells are recorded.",
            "One-way hybrid without replay feedback; parameters uncalibrated.",
            "The visible body is not physically registered to these EM coordinates.",
        ],
        "units": {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"},
    }
    # These are the selected source compartments, not all compartments or all
    # cells. Keep extrema before decimation so extreme numerical responses do
    # not disappear from the summary.
    voltage_keys = [f"source_{i}_voltage_mv" for i in range(len(metadata["source_cells"]))]
    if voltage_keys and all(key in arrays for key in voltage_keys):
        output["source_voltage_range_mv"] = {
            "minimum": min(float(np.min(arrays[key])) for key in voltage_keys),
            "maximum": max(float(np.max(arrays[key])) for key in voltage_keys),
        }
    ranges = [source.get("all_voltage_range_mv") for source in metadata["source_cells"]
              if isinstance(source, dict)]
    if len(ranges) == len(voltage_keys) and ranges and all(value is not None for value in ranges):
        output["source_all_compartments_voltage_range_mv"] = {
            "minimum": min(value["minimum"] for value in ranges),
            "maximum": max(value["maximum"] for value in ranges),
        }
        # A maximum alone does not prove an upward crossing or its time. It
        # does identify cells whose unobserved compartments warrant review.
        event_keys = [f"source_{i}_event_ticks_ms" for i in range(len(ranges))]
        if (all(key in arrays for key in event_keys)
                and all(isinstance(source.get("selection"), dict)
                        and "threshold_mv" in source["selection"]
                        for source in metadata["source_cells"])):
            output["source_unobserved_threshold_candidates"] = sum(
                len(arrays[key]) == 0
                and voltage_range["maximum"] >= source["selection"]["threshold_mv"]
                for key, voltage_range, source in zip(
                    event_keys, ranges, metadata["source_cells"], strict=True
                )
            )
    if "replay_all_voltage_range_mv" in metadata:
        output["replay_all_compartments_voltage_range_mv"] = metadata["replay_all_voltage_range_mv"]
    diagnostics = [source.get("crossing_diagnostics") for source in metadata["source_cells"]
                   if isinstance(source, dict)]
    if (diagnostics and len(diagnostics) == len(metadata["source_cells"])
            and all(item is not None for item in diagnostics)):
        output["source_compartment_crossings"] = {
            "sources_checked": len(diagnostics),
            "outside_selected_only": sum(
                item["compartments_with_upward_crossing"] > 0 and item["selected_crossings"] == 0
                for item in diagnostics
            ),
            "earlier_than_selected": sum(
                item["selected_first_crossing_sample_ms"] is not None
                and item["earliest_crossing_sample_ms"]
                < item["selected_first_crossing_sample_ms"]
                for item in diagnostics
            ),
            "initial_above_sources": sum(item["initial_at_or_above_threshold"] > 0
                                         for item in diagnostics),
        }
    if metadata["configuration"].get("retain_compartment_crossings") is True:
        samples, bodies, compartments, positions = [], [], [], []
        sources_with_unrepresented_bins = 0
        unrepresented_bins = 0
        for i, source in enumerate(metadata["source_cells"]):
            segment = arrays[f"source_{i}_crossing_compartment_indices"]
            tick = arrays[f"source_{i}_crossing_sample_indices"]
            location = arrays[f"source_{i}_crossing_midpoints_um"]
            samples.append(tick)
            bodies.append(np.full(len(tick), source["selection"]["body_id"], dtype=np.int64))
            compartments.append(segment)
            positions.append(location[segment])
            sample_times = time[tick]
            nearest = np.rint(sample_times)
            snapped = np.where(np.abs(sample_times - nearest) <= 1e-9, nearest, sample_times)
            snapped = np.where(snapped == 0, sample_times, snapped)
            sample_bins = set(np.ceil(snapped).astype(np.int64).tolist())
            selected_bins = set(np.asarray(arrays[f"source_{i}_event_ticks_ms"]).tolist())
            unrepresented = sample_bins - selected_bins
            sources_with_unrepresented_bins += bool(unrepresented)
            unrepresented_bins += len(unrepresented)
        all_samples = np.concatenate(samples)
        all_bodies = np.concatenate(bodies)
        all_compartments = np.concatenate(compartments)
        all_positions = np.concatenate(positions)
        total = len(all_samples)
        order = np.lexsort((all_compartments, all_bodies, all_samples))
        chosen = order[np.linspace(0, total - 1, min(total, 1000), dtype=int)] if total else order
        output["compartment_events"] = {
            "total": total,
            "shown": len(chosen),
            "selection": "uniform rank sample ordered by time, body and compartment",
            "events": [[str(int(all_bodies[i])), float(time[all_samples[i]]),
                        int(all_compartments[i]),
                        *[float(value) for value in all_positions[i]]] for i in chosen],
        }
        output["compartment_bin_coverage"] = {
            "sources_checked": len(metadata["source_cells"]),
            "sources_with_unrepresented_bins": sources_with_unrepresented_bins,
            "unrepresented_source_bins": unrepresented_bins,
        }
    if has_acquisition:
        output["acquisition"] = {
            "filtered_total_uv": arrays["filtered_total_uv"][indices].tolist(),
            "valid_samples": [bins_valid[int(index)] for index in indices],
            "saturated_samples": [bins_saturated[int(index)] for index in indices],
            "mask_scope": "conservative aggregation over the source bin",
            "mask_intervals": intervals,
            "settings": metadata["acquisition_settings"],
        }
    return output


def export_field_graph_preview(directory, graph, *, bins=512):
    """Write a preview only after the underlying result has been verified."""
    payload = (
        json.dumps(
            field_graph_preview(directory, graph, bins=bins),
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path = directory / "field-graph-preview.json"
    with path.open("xb") as output:
        output.write(payload)
    return {"name": path.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
