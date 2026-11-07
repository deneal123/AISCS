"""Validate experimental field-graph output before accepting owned artifacts."""

from __future__ import annotations

import math
import re


class InvalidFieldGraphManifest(ValueError):
    pass


def validate_field_graph_manifest(manifest, *, configuration_sha256, retain_currents=None,
                                  retain_state_contrast=None):
    expected = {
        "graph.bin",
        "replay-evidence.jsonl",
        "replay-provenance.jsonl",
        "metadata.json",
        "signals.npz",
        "field-graph-preview.json",
    }
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "field-graph-replay-manifest-v1"
        or manifest.get("kind") != "field-graph-replay"
        or not isinstance(configuration_sha256, str)
        or not re.fullmatch(r"[a-f0-9]{64}", configuration_sha256)
        or manifest.get("configuration_sha256") != configuration_sha256
    ):
        raise InvalidFieldGraphManifest("field_graph_identity")
    archive_sha = manifest.get("current_manifest_sha256")
    if "current_manifest_sha256" in manifest and archive_sha is None:
        raise InvalidFieldGraphManifest("field_graph_current_archive")
    if retain_currents is not None and (archive_sha is not None) != retain_currents:
        raise InvalidFieldGraphManifest("field_graph_current_archive")
    if archive_sha is not None:
        if not isinstance(archive_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", archive_sha):
            raise InvalidFieldGraphManifest("field_graph_current_archive")
        expected.add("currents.zip")
    files = manifest.get("files")
    state_names = {'state-contrast.bin', 'state-contrast.json', 'state-source-manifest.json'}
    if isinstance(files, list):
        present = {item.get('name') for item in files if isinstance(item, dict)}
        has_state = bool(state_names & present)
        if retain_state_contrast is not None and has_state != retain_state_contrast:
            raise InvalidFieldGraphManifest('field_graph_state_contrast')
        if has_state:
            expected.update(state_names)
    if not isinstance(files, list) or len(files) != len(expected):
        raise InvalidFieldGraphManifest("field_graph_files")
    names = set()
    for item in files:
        if not isinstance(item, dict):
            raise InvalidFieldGraphManifest("field_graph_files")
        name, size, digest = item.get("name"), item.get("bytes"), item.get("sha256")
        if (
            not isinstance(name, str)
            or name not in expected
            or name in names
            or type(size) is not int
            or not 1 <= size <= 256 * 1024 * 1024
            or (name == "field-graph-preview.json" and size > 1024 * 1024)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise InvalidFieldGraphManifest("field_graph_files")
        names.add(name)
    if names != expected:
        raise InvalidFieldGraphManifest("field_graph_files")


def validate_field_graph_preview(preview, configuration):
    """Require finite aligned traces, conservative masks and matching run dimensions."""
    try:
        simulation = configuration["simulation"]
        duration, dt = simulation["duration_ms"], simulation["dt_ms"]
        times, neural, total = preview["time_ms"], preview["neural_uv"], preview["total_uv"]
        stimulus = preview["stimulus_fraction"]
        original, shown = preview["samples"], preview["shown_samples"]
        source, replay = configuration["source_cells"], configuration["replay_ids"]
        spikes = preview["network_spikes_by_ms"]
        if (
            type(duration) not in (int, float)
            or type(dt) not in (int, float)
            or not math.isfinite(duration)
            or not math.isfinite(dt)
            or duration <= 0
            or dt <= 0
            or not float(duration).is_integer()
            or not isinstance(spikes, list)
            or len(spikes) != int(duration) + 1
            or any(type(value) is not int or value < 0 for value in spikes)
            or spikes[0] != 0
            or type(original) is not int
            or original != round(duration / dt) + 1
            or type(shown) is not int
            or not 2 <= shown <= min(original, 4096)
            or not all(
                isinstance(values, list) and len(values) == shown
                for values in (times, neural, total, stimulus)
            )
            or any(
                type(value) not in (int, float) or not math.isfinite(value)
                for values in (times, neural, total, stimulus)
                for value in values
            )
            or not math.isclose(times[0], 0, abs_tol=1e-8)
            or not math.isclose(times[-1], duration, rel_tol=0, abs_tol=1e-8)
            or any(a >= b for a, b in zip(times, times[1:], strict=False))
            or not isinstance(source, list)
            or not isinstance(replay, list)
            or type(preview["source_cells"]) is not int
            or type(preview["replay_cells"]) is not int
            or preview["source_cells"] != len(source)
            or preview["replay_cells"] != len(replay)
            or preview["units"] != {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"}
            or not isinstance(preview["limitations"], list)
            or not all(isinstance(item, str) for item in preview["limitations"])
        ):
            raise InvalidFieldGraphManifest("field_graph_preview")
        for key in ("source_voltage_range_mv", "source_all_compartments_voltage_range_mv",
                    "replay_all_compartments_voltage_range_mv"):
            voltage = preview.get(key)
            if voltage is None:
                continue
            if (not isinstance(voltage, dict) or set(voltage) != {"minimum", "maximum"}
                    or any(type(voltage[key]) not in (int, float) or not math.isfinite(voltage[key])
                           for key in ("minimum", "maximum"))
                    or voltage["minimum"] > voltage["maximum"]):
                raise InvalidFieldGraphManifest("field_graph_preview")
        selected = preview.get("source_voltage_range_mv")
        full = preview.get("source_all_compartments_voltage_range_mv")
        if (full is not None and (selected is None or full["minimum"] > selected["minimum"]
                                  or full["maximum"] < selected["maximum"])):
            raise InvalidFieldGraphManifest("field_graph_preview")
        if "source_unobserved_threshold_candidates" in preview:
            candidates = preview["source_unobserved_threshold_candidates"]
            if type(candidates) is not int or not 0 <= candidates <= len(source) or full is None:
                raise InvalidFieldGraphManifest("field_graph_preview")
        if "source_compartment_crossings" in preview:
            summary = preview["source_compartment_crossings"]
            if (not isinstance(summary, dict)
                    or set(summary) != {"sources_checked", "outside_selected_only",
                                       "earlier_than_selected", "initial_above_sources"}
                    or type(summary["sources_checked"]) is not int
                    or summary["sources_checked"] != len(source)
                    or any(type(summary[key]) is not int or not 0 <= summary[key] <= len(source)
                           for key in ("outside_selected_only", "earlier_than_selected",
                                       "initial_above_sources"))
                    or summary["outside_selected_only"] + summary["earlier_than_selected"]
                    > len(source)):
                raise InvalidFieldGraphManifest("field_graph_preview")
            if ("source_unobserved_threshold_candidates" in preview
                    and summary["outside_selected_only"]
                    > preview["source_unobserved_threshold_candidates"]):
                raise InvalidFieldGraphManifest("field_graph_preview")
        if (configuration.get("retain_compartment_crossings") is True) != (
                "compartment_events" in preview):
            raise InvalidFieldGraphManifest("field_graph_preview")
        if "compartment_bin_coverage" in preview:
            coverage = preview["compartment_bin_coverage"]
            duration = configuration["simulation"]["duration_ms"]
            if ("compartment_events" not in preview or not isinstance(coverage, dict)
                    or set(coverage) != {"sources_checked", "sources_with_unrepresented_bins",
                                         "unrepresented_source_bins"}
                    or type(coverage["sources_checked"]) is not int
                    or coverage["sources_checked"] != len(source)
                    or type(coverage["sources_with_unrepresented_bins"]) is not int
                    or not 0 <= coverage["sources_with_unrepresented_bins"] <= len(source)
                    or type(coverage["unrepresented_source_bins"]) is not int
                    or not (coverage["sources_with_unrepresented_bins"]
                            <= coverage["unrepresented_source_bins"] <= len(source) * duration)
                    or ((coverage["sources_with_unrepresented_bins"] == 0)
                        != (coverage["unrepresented_source_bins"] == 0))):
                raise InvalidFieldGraphManifest("field_graph_preview")
        if "compartment_events" in preview:
            event_data = preview["compartment_events"]
            if (not isinstance(event_data, dict)
                    or set(event_data) != {"total", "shown", "selection", "events"}
                    or type(event_data["total"]) is not int
                    or not 0 <= event_data["total"] <= 1_000_000
                    or type(event_data["shown"]) is not int
                    or event_data["shown"] != min(event_data["total"], 1000)
                    or event_data["selection"] != (
                        "uniform rank sample ordered by time, body and compartment")
                    or not isinstance(event_data["events"], list)
                    or len(event_data["events"]) != event_data["shown"]):
                raise InvalidFieldGraphManifest("field_graph_preview")
            if ("compartment_bin_coverage" in preview
                    and preview["compartment_bin_coverage"]["unrepresented_source_bins"]
                    > event_data["total"]):
                raise InvalidFieldGraphManifest("field_graph_preview")
            allowed = {str(item["body_id"]) for item in source}
            previous_time = -1.0
            for event in event_data["events"]:
                if (not isinstance(event, list) or len(event) != 6
                        or not isinstance(event[0], str) or event[0] not in allowed
                        or type(event[1]) not in (int, float) or not math.isfinite(event[1])
                        or not 0 < event[1] <= duration or event[1] < previous_time
                        or not math.isclose(event[1] / dt, round(event[1] / dt), abs_tol=1e-6)
                        or type(event[2]) is not int or event[2] < 0
                        or any(type(value) not in (int, float) or not math.isfinite(value)
                               for value in event[3:])):
                    raise InvalidFieldGraphManifest("field_graph_preview")
                previous_time = event[1]
        acquisition = preview.get("acquisition")
        if (configuration.get("acquisition") is None) != (acquisition is None):
            raise InvalidFieldGraphManifest("field_graph_preview")
        if acquisition is not None:
            filtered, valid, saturated = (
                acquisition[key]
                for key in ("filtered_total_uv", "valid_samples", "saturated_samples")
            )
            if (
                not all(
                    isinstance(values, list) and len(values) == shown
                    for values in (filtered, valid, saturated)
                )
                or any(
                    type(value) not in (int, float) or not math.isfinite(value)
                    for value in filtered
                )
                or any(type(value) is not bool for value in valid + saturated)
                or any(v and s for v, s in zip(valid, saturated, strict=True))
                or acquisition.get("mask_scope") != "conservative aggregation over the source bin"
                or not isinstance(acquisition.get("settings"), dict)
                or any(
                    acquisition["settings"].get(key) != configuration["acquisition"].get(key)
                    for key in ("low_hz", "high_hz", "recovery_ms", "clip_uv")
                )
            ):
                raise InvalidFieldGraphManifest("field_graph_preview")
            intervals = acquisition.get("mask_intervals")
            if not isinstance(intervals, list) or not 1 <= len(intervals) <= 512:
                raise InvalidFieldGraphManifest("field_graph_preview")
            previous = 0.0
            for interval in intervals:
                start, end = interval["start_ms"], interval["end_ms"]
                is_valid, is_saturated = interval["valid"], interval["saturated"]
                if (type(start) not in (int, float) or type(end) not in (int, float)
                        or not math.isfinite(start) or not math.isfinite(end)
                        or not math.isclose(start, previous, rel_tol=0, abs_tol=1e-8)
                        or end < start or end > duration + 1e-8
                        or type(is_valid) is not bool or type(is_saturated) is not bool
                        or (is_valid and is_saturated)):
                    raise InvalidFieldGraphManifest("field_graph_preview")
                previous = end
            if not math.isclose(previous, duration, rel_tol=0, abs_tol=1e-8):
                raise InvalidFieldGraphManifest("field_graph_preview")
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        raise InvalidFieldGraphManifest("field_graph_preview") from exc
