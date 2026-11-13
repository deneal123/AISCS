"""Persist an experimental hybrid result with complete self-checking evidence."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path

import numpy as np

from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.connectome.forced_network import threshold_crossing_ticks
from service.infrastructure.stimulation.acquisition import acquire_channel
from service.infrastructure.stimulation.recording.current_archive import _stream_sha
from service.infrastructure.stimulation.synaptic_replay import read_verified_spikes


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _validate_voltage_range(value, trace=None):
    if (not isinstance(value, dict) or set(value) != {"minimum", "maximum"}
            or any(type(value[key]) not in (int, float) or not np.isfinite(value[key])
                   for key in ("minimum", "maximum"))
            or value["minimum"] > value["maximum"]
            or (trace is not None and (value["minimum"] > float(np.min(trace))
                                       or value["maximum"] < float(np.max(trace))))):
        raise ValueError("Invalid source-cell full voltage range")


def _validate_crossing_diagnostics(value, time, trace, threshold, *, provenance=None,
                                   sampling=None):
    keys = {"compartments", "initial_at_or_above_threshold", "compartments_with_upward_crossing",
            "earliest_crossing_sample_ms", "selected_crossings",
            "selected_first_crossing_sample_ms"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Invalid compartment crossing diagnostics")
    count = value["compartments"]
    initial = value["initial_at_or_above_threshold"]
    crossed = value["compartments_with_upward_crossing"]
    selected_count = value["selected_crossings"]
    if (type(count) is not int or count < 1 or type(initial) is not int
            or not 0 <= initial <= count or type(crossed) is not int or not 0 <= crossed <= count
            or type(selected_count) is not int or selected_count < 0):
        raise ValueError("Invalid compartment crossing diagnostics")
    if isinstance(provenance, dict) and ("vertices" in provenance or "components" in provenance):
        vertices, components = provenance.get("vertices"), provenance.get("components")
        nseg = sampling.get("nseg_per_edge") if isinstance(sampling, dict) else None
        selected = sampling.get("result_segment_index") if isinstance(sampling, dict) else None
        if (type(vertices) is not int or type(components) is not int
                or not 1 <= components < vertices or type(nseg) is not int or nseg < 1
                or count != (vertices - components) * nseg
                or type(selected) is not int or not 0 <= selected < count):
            raise ValueError("Compartment diagnostics do not match morphology")
    indices = np.flatnonzero((trace[:-1] < threshold) & (trace[1:] >= threshold)) + 1
    selected_first = None if len(indices) == 0 else float(time[indices[0]])
    earliest = value["earliest_crossing_sample_ms"]
    if (selected_count != len(indices)
            or value["selected_first_crossing_sample_ms"] != selected_first
            or (crossed == 0) != (earliest is None)
            or (selected_count > 0 and crossed == 0)
            or (trace[0] >= threshold and initial == 0)
            or (earliest is not None and (type(earliest) not in (int, float)
                or not np.isfinite(earliest) or earliest < time[1] or earliest > time[-1]
                or not np.any(time[1:] == earliest)
                or (selected_first is not None and earliest > selected_first)))):
        raise ValueError("Inconsistent compartment crossing diagnostics")


def _validate_compartment_crossings(events, diagnostic, sampling, time, trace, threshold):
    if not isinstance(events, dict) or set(events) != {
        "compartment_indices", "sample_indices", "midpoints_um"
    } or not isinstance(diagnostic, dict) or not isinstance(sampling, dict):
        raise ValueError("Invalid compartment crossing archive")
    segments, samples, positions = (np.asarray(events[key]) for key in (
        "compartment_indices", "sample_indices", "midpoints_um"))
    count = diagnostic.get("compartments")
    selected = sampling.get("result_segment_index")
    if (type(count) is not int or count < 1 or type(selected) is not int
            or not 0 <= selected < count or segments.ndim != 1 or samples.shape != segments.shape
            or segments.dtype.kind not in "iu" or samples.dtype.kind not in "iu"
            or len(segments) > 1_000_000 or positions.shape != (count, 3)
            or positions.dtype.kind not in "fiu" or not np.isfinite(positions).all()
            or np.any(segments < 0) or np.any(segments >= count)
            or np.any(samples < 1) or np.any(samples >= len(time))):
        raise ValueError("Invalid compartment crossing archive")
    if (len(segments) > 1 and (np.any(segments[1:] < segments[:-1])
            or np.any((segments[1:] == segments[:-1]) & (samples[1:] <= samples[:-1])))):
        raise ValueError("Invalid compartment crossing order")
    expected_selected = np.flatnonzero((trace[:-1] < threshold) & (trace[1:] >= threshold)) + 1
    if (not np.array_equal(samples[segments == selected], expected_selected)
            or len(np.unique(segments)) != diagnostic["compartments_with_upward_crossing"]
            or (None if len(samples) == 0 else float(time[int(np.min(samples))]))
            != diagnostic["earliest_crossing_sample_ms"]):
        raise ValueError("Compartment crossing archive contradicts diagnostics")
    return len(segments)


def _verify_acquisition(arrays, settings, configuration):
    if not isinstance(configuration, dict) or set(configuration) != {
        "low_hz",
        "high_hz",
        "recovery_ms",
        "clip_uv",
    }:
        raise ValueError("Invalid acquisition configuration")
    expected = acquire_channel(
        arrays["time_ms"],
        arrays["neural_uv"],
        arrays["stimulus_artifact_uv"],
        arrays["stimulus_fraction"],
        **configuration,
    )
    if settings != expected["settings"]:
        raise ValueError("Acquisition settings differ from recalculated settings")
    for key in ("valid_samples", "saturated_samples"):
        if not np.array_equal(arrays[key], expected[key]):
            raise ValueError("Acquisition mask differs from recalculated mask")
    if not np.allclose(
        arrays["filtered_total_uv"], expected["filtered_total_uv"], rtol=1e-12, atol=1e-12
    ):
        raise ValueError("Acquisition output differs from recalculated signal")


def export_field_graph_replay(result, graph, directory: Path, *, evidence, provenance):
    """Create a new artifact directory; the manifest is published last.

    The caller must discard an incomplete directory if writing fails. Source
    and replay cell evidence remains separate; this is a one-way model.
    """
    replay, source, recording = result["replay"], result["source"], result["recording"]
    if (
        not isinstance(evidence, bytes)
        or not isinstance(provenance, bytes)
        or _sha(evidence) != replay["replay_evidence_sha256"]
        or _sha(provenance) != replay["cell_provenance_sha256"]
        or not replay["replay_evidence_exported"]
        or not replay["cell_provenance_exported"]
    ):
        raise ValueError("Replay evidence or provenance does not match its digest")
    try:
        entries = [json.loads(line) for line in evidence.splitlines()]
        provenance_entries = [json.loads(line) for line in provenance.splitlines()]
        replay_ids = result["configuration"]["replay_ids"]
        if [int(entry["mapping"]["body_id"]) for entry in entries] != replay_ids or [
            int(entry["body_id"]) for entry in provenance_entries
        ] != replay_ids:
            raise ValueError("Replay evidence cell order differs from configuration")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed replay evidence or provenance") from exc
    binary, description, digest = encode_forced_spikes(graph, source["network"])
    if (
        digest != recording["graph_stream_sha256"]
        or description != result["graph_description"]
        or replay["source_sha256"] != digest
    ):
        raise ValueError("Graph event stream differs from replay")
    if any(
        entry.get("connectome_sha256") != digest or entry.get("provenance") != cell
        for entry, cell in zip(entries, provenance_entries, strict=True)
    ):
        raise ValueError("Replay evidence is not bound to the graph and cell provenance")
    time = np.asarray(recording["time_ms"], dtype=float)
    signal = {
        key: np.asarray(recording[key], dtype=float)
        for key in ("neural_uv", "stimulus_artifact_uv", "stimulus_fraction", "total_uv")
    }
    if (
        time.ndim != 1
        or len(time) < 2
        or not np.isfinite(time).all()
        or np.any(np.diff(time) <= 0)
        or any(
            values.shape != time.shape or not np.isfinite(values).all()
            for values in signal.values()
        )
        or not np.allclose(
            signal["total_uv"],
            signal["neural_uv"] + signal["stimulus_artifact_uv"],
            rtol=1e-12,
            atol=1e-12,
        )
    ):
        raise ValueError("Invalid combined signal")
    source_neural = np.asarray(source["recording"]["neural_uv"], dtype=float)
    replay_neural = np.asarray(replay["neural_uv"], dtype=float)
    if (
        source_neural.shape != time.shape
        or replay_neural.shape != time.shape
        or not np.isfinite(source_neural).all()
        or not np.isfinite(replay_neural).all()
        or not np.allclose(
            signal["neural_uv"], source_neural + replay_neural, rtol=1e-12, atol=1e-12
        )
    ):
        raise ValueError("Cell populations do not sum to the combined neural signal")
    arrays = {
        "time_ms": time,
        **signal,
        "source_neural_uv": source_neural,
        "replay_neural_uv": replay_neural,
    }
    source_metadata = []
    retained_events = 0
    retain_crossings = result["configuration"].get("retain_compartment_crossings") is True
    for index, cell in enumerate(source["sources"]):
        expected_morphology = cell["selection"].get("morphology_sha256")
        if (expected_morphology is not None
                and cell["provenance"].get("morphology_sha256") != expected_morphology):
            raise ValueError("Source morphology digest mismatch")
        cell_time = np.asarray(cell["time_ms"], dtype=float)
        voltage = np.asarray(cell["voltage_mv"], dtype=float)
        ticks = np.asarray(cell["event_ticks_ms"])
        if (
            not np.array_equal(cell_time, time)
            or voltage.shape != time.shape
            or not np.isfinite(voltage).all()
            or ticks.ndim != 1
            or ticks.dtype.kind not in "iu"
        ):
            raise ValueError("Invalid source-cell trace")
        arrays[f"source_{index}_voltage_mv"] = voltage
        arrays[f"source_{index}_event_ticks_ms"] = ticks
        source_metadata.append(
            {
                "selection": cell["selection"],
                "sampling": cell["sampling"],
                "provenance": cell["provenance"],
            }
        )
        full_range = cell.get("all_voltage_range_mv")
        if full_range is not None:
            _validate_voltage_range(full_range, voltage)
            source_metadata[-1]["all_voltage_range_mv"] = full_range
        diagnostic = cell.get("crossing_diagnostics")
        if diagnostic is not None:
            _validate_crossing_diagnostics(diagnostic, cell_time, voltage,
                                           cell["selection"]["threshold_mv"],
                                           provenance=cell["provenance"], sampling=cell["sampling"])
            source_metadata[-1]["crossing_diagnostics"] = diagnostic
        crossing_data = cell.get("compartment_crossings")
        if (crossing_data is not None) != retain_crossings:
            raise ValueError("Compartment crossing retention does not match configuration")
        if retain_crossings:
            count = _validate_compartment_crossings(crossing_data, diagnostic, cell["sampling"],
                                                    cell_time, voltage,
                                                    cell["selection"]["threshold_mv"])
            retained_events += count
            if retained_events > 1_000_000:
                raise ValueError("Compartment crossing event limit exceeded")
            for field, value in crossing_data.items():
                arrays[f"source_{index}_crossing_{field}"] = np.asarray(value)
            source_metadata[-1]["compartment_crossings"] = {
                "format": "compartment-crossings-v1", "events": count,
            }
    acquired = result["acquisition"]
    if (acquired is None) != (result["configuration"].get("acquisition") is None):
        raise ValueError("Acquisition output does not match configuration")
    if acquired is not None:
        for field in ("filtered_total_uv", "valid_samples", "saturated_samples"):
            value = np.asarray(acquired[field])
            if (
                value.shape != time.shape
                or (field.endswith("samples") and value.dtype != np.bool_)
                or (field == "filtered_total_uv" and not np.isfinite(value).all())
            ):
                raise ValueError("Invalid acquired signal")
            arrays[field] = value
        _verify_acquisition(
            arrays, acquired["settings"], result["configuration"].get("acquisition")
        )
    metadata = {
        "format": "field-graph-replay-v1",
        "configuration": result["configuration"],
        "graph_description": description,
        "source_cells": source_metadata,
        "replay_evidence_sha256": _sha(evidence),
        "replay_provenance_sha256": _sha(provenance),
        "graph_sha256": digest,
        "acquisition_settings": None if acquired is None else acquired["settings"],
        "interpretation": result["interpretation"],
    }
    replay_range = replay.get("all_voltage_range_mv")
    if replay_range is not None:
        _validate_voltage_range(replay_range)
        metadata["replay_all_voltage_range_mv"] = replay_range
    metadata_bytes = (
        json.dumps(
            metadata, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")
    directory.mkdir(parents=True, exist_ok=False)
    payloads = {
        "graph.bin": binary,
        "replay-evidence.jsonl": evidence,
        "replay-provenance.jsonl": provenance,
        "metadata.json": metadata_bytes,
    }
    for name, data in payloads.items():
        (directory / name).write_bytes(data)
    signal_path = directory / "signals.npz"
    with signal_path.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    payloads["signals.npz"] = signal_path.read_bytes()
    manifest = {
        "format": "field-graph-replay-manifest-v1",
        "files": [
            {"name": name, "bytes": len(data), "sha256": _sha(data)}
            for name, data in sorted(payloads.items())
        ],
    }
    with (directory / "manifest.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return manifest


def load_verified_field_graph_replay(directory: Path, graph):
    """Verify file hashes, graph identity, source events and combined signal."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    names = {
        "graph.bin",
        "replay-evidence.jsonl",
        "replay-provenance.jsonl",
        "metadata.json",
        "signals.npz",
    }
    optional_preview = "field-graph-preview.json"
    optional_archive = "currents.zip"
    state_names = {"state-contrast.bin", "state-contrast.json", "state-source-manifest.json"}
    files = manifest.get("files") if isinstance(manifest, dict) else None
    present = ({item.get('name') for item in files if isinstance(item, dict)}
               if isinstance(files, list) else set())
    state_present = bool(state_names & present)
    expected = names | ({optional_preview} if optional_preview in present else set())
    expected |= {optional_archive} if optional_archive in present else set()
    expected |= state_names if state_present else set()
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "field-graph-replay-manifest-v1"
        or not isinstance(files, list)
        or len(files) != len(expected)
        or any(not isinstance(item, dict) for item in files)
        or len({item.get("name") for item in files}) != len(files)
        or present != expected
        or (optional_archive in present and optional_preview not in present)
        or (state_present and optional_preview not in present)
        or (optional_archive in {item.get("name") for item in files}) != (
            "current_manifest_sha256" in manifest
        )
        or ("current_manifest_sha256" in manifest and (
            not isinstance(manifest["current_manifest_sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", manifest["current_manifest_sha256"]) is None
        ))
    ):
        raise ValueError("Invalid hybrid artifact manifest")
    payloads = {}
    for item in files:
        if item["name"] == optional_archive:
            archive = directory / optional_archive
            with archive.open("rb") as stream:
                digest = _stream_sha(stream)
            if (type(item.get("bytes")) is not int or item["bytes"] != archive.stat().st_size
                    or item.get("sha256") != digest):
                raise ValueError("Hybrid artifact checksum mismatch")
            continue
        data = (directory / item["name"]).read_bytes()
        if (
            type(item.get("bytes")) is not int
            or item["bytes"] != len(data)
            or item.get("sha256") != _sha(data)
        ):
            raise ValueError("Hybrid artifact checksum mismatch")
        payloads[item["name"]] = data
    metadata = json.loads(payloads["metadata.json"])
    if (
        metadata.get("format") != "field-graph-replay-v1"
        or _sha(payloads["graph.bin"]) != metadata["graph_sha256"]
        or _sha(payloads["replay-evidence.jsonl"]) != metadata["replay_evidence_sha256"]
        or _sha(payloads["replay-provenance.jsonl"]) != metadata["replay_provenance_sha256"]
    ):
        raise ValueError("Hybrid artifact identities differ")
    if state_present:
        from service.infrastructure.connectome.state_contrast_export import decode_state_contrast

        base = json.loads(payloads['state-source-manifest.json'])
        final_core = {item['name']: item for item in files if item['name'] in names}
        base_files = base.get('files') if isinstance(base, dict) else None
        if (not isinstance(base, dict) or base.get('format') != 'field-graph-replay-manifest-v1'
                or not isinstance(base_files, list) or len(base_files) != len(names)
                or any(not isinstance(item, dict) for item in base_files)
                or {item.get('name') for item in base_files} != names
                or any(final_core[item['name']] != item for item in base_files)):
            raise ValueError('State contrast source manifest differs')
        decode_state_contrast(
            payloads['state-contrast.bin'], json.loads(payloads['state-contrast.json']),
            expected_field_manifest_sha256=_sha(payloads['state-source-manifest.json']),
            expected_graph_manifest_sha256=graph.provenance['manifest_sha256'],
            expected_graph_sha256=metadata['graph_sha256'], graph_ids=graph.ids)
    source_meta = metadata["source_cells"]
    source_ids = [item["selection"]["body_id"] for item in source_meta]
    graph_spikes = read_verified_spikes(
        payloads["graph.bin"],
        metadata["graph_description"],
        metadata["graph_sha256"],
        graph.ids,
        graph.provenance["manifest_sha256"],
        source_ids,
    )
    evidence = [json.loads(line) for line in payloads["replay-evidence.jsonl"].splitlines()]
    provenance = [json.loads(line) for line in payloads["replay-provenance.jsonl"].splitlines()]
    replay_ids = metadata["configuration"]["replay_ids"]
    if [int(item["mapping"]["body_id"]) for item in evidence] != replay_ids or [
        int(item["body_id"]) for item in provenance
    ] != replay_ids:
        raise ValueError("Replay cell identity mismatch")
    if any(
        entry.get("connectome_sha256") != metadata["graph_sha256"]
        or entry.get("provenance") != cell
        for entry, cell in zip(evidence, provenance, strict=True)
    ):
        raise ValueError("Replay evidence is not bound to the graph and cell provenance")
    if [item["selection"] for item in source_meta] != metadata["configuration"]["source_cells"]:
        raise ValueError("Source cell identity mismatch")
    for source in source_meta:
        expected_morphology = source["selection"].get("morphology_sha256")
        if (expected_morphology is not None
                and source.get("provenance", {}).get("morphology_sha256") != expected_morphology):
            raise ValueError("Source morphology digest mismatch")
        requested = source["selection"].get("sampling_fraction")
        if requested is None:
            continue
        sampling = source.get("sampling", {})
        nseg = metadata["configuration"]["simulation_parameters"].get("nseg_per_edge", 1)
        if (type(nseg) is not int or nseg < 1 or nseg % 2 != 1
                or type(requested) not in (int, float) or not 0 <= requested <= 1
                or sampling.get("requested_edge_fraction") != requested
                or sampling.get("nseg_per_edge") != nseg
                or sampling.get("edge_fraction") != (
                    min(int(requested * nseg), nseg - 1) + .5) / nseg
                or type(sampling.get("result_segment_index")) is not int
                or sampling["result_segment_index"] < 0):
            raise ValueError("Source sampling location mismatch")
    with np.load(io.BytesIO(payloads["signals.npz"]), allow_pickle=False) as loaded:
        arrays = {name: loaded[name] for name in loaded.files}
    required = {
        "time_ms",
        "neural_uv",
        "stimulus_artifact_uv",
        "stimulus_fraction",
        "total_uv",
        "source_neural_uv",
        "replay_neural_uv",
    }
    required |= {
        f"source_{i}_{field}"
        for i in range(len(source_meta))
        for field in ("voltage_mv", "event_ticks_ms")
    }
    retain_crossings = metadata["configuration"].get("retain_compartment_crossings") is True
    if retain_crossings:
        required |= {
            f"source_{i}_crossing_{field}"
            for i in range(len(source_meta))
            for field in ("compartment_indices", "sample_indices", "midpoints_um")
        }
    if (metadata["acquisition_settings"] is None) != (
        metadata["configuration"].get("acquisition") is None
    ):
        raise ValueError("Acquisition output does not match configuration")
    if metadata["acquisition_settings"] is not None:
        required |= {"filtered_total_uv", "valid_samples", "saturated_samples"}
    if set(arrays) != required:
        raise ValueError("Invalid hybrid signal fields")
    time = arrays["time_ms"]
    if (
        time.ndim != 1
        or len(time) < 2
        or not np.isfinite(time).all()
        or np.any(np.diff(time) <= 0)
        or any(
            arrays[key].shape != time.shape or not np.isfinite(arrays[key]).all()
            for key in (
                "neural_uv",
                "stimulus_artifact_uv",
                "stimulus_fraction",
                "total_uv",
                "source_neural_uv",
                "replay_neural_uv",
            )
        )
        or not np.allclose(
            arrays["neural_uv"],
            arrays["source_neural_uv"] + arrays["replay_neural_uv"],
            rtol=1e-12,
            atol=1e-12,
        )
        or not np.allclose(
            arrays["total_uv"],
            arrays["neural_uv"] + arrays["stimulus_artifact_uv"],
            rtol=1e-12,
            atol=1e-12,
        )
    ):
        raise ValueError("Invalid hybrid signal")
    duration = metadata["graph_description"]["duration_ms"]
    retained_events = 0
    for i, source in enumerate(source_meta):
        if "all_voltage_range_mv" in source:
            _validate_voltage_range(source["all_voltage_range_mv"],
                                    arrays[f"source_{i}_voltage_mv"])
        if "crossing_diagnostics" in source:
            _validate_crossing_diagnostics(source["crossing_diagnostics"], time,
                                           arrays[f"source_{i}_voltage_mv"],
                                           source["selection"]["threshold_mv"],
                                           provenance=source["provenance"],
                                           sampling=source["sampling"])
        crossing_meta = source.get("compartment_crossings")
        if (crossing_meta is not None) != retain_crossings:
            raise ValueError("Compartment crossing retention does not match configuration")
        if retain_crossings:
            crossing_data = {field: arrays[f"source_{i}_crossing_{field}"] for field in (
                "compartment_indices", "sample_indices", "midpoints_um")}
            count = _validate_compartment_crossings(
                crossing_data, source.get("crossing_diagnostics"), source.get("sampling"), time,
                arrays[f"source_{i}_voltage_mv"], source["selection"]["threshold_mv"],
            )
            if crossing_meta != {"format": "compartment-crossings-v1", "events": count}:
                raise ValueError("Invalid compartment crossing archive metadata")
            retained_events += count
            if retained_events > 1_000_000:
                raise ValueError("Compartment crossing event limit exceeded")
        ticks = threshold_crossing_ticks(
            time,
            arrays[f"source_{i}_voltage_mv"],
            threshold_mv=source["selection"]["threshold_mv"],
            duration_ms=duration,
        )
        if not np.array_equal(ticks, arrays[f"source_{i}_event_ticks_ms"]):
            raise ValueError("Source voltage and event times differ")
        if not np.array_equal(ticks, graph_spikes[str(source_ids[i])]):
            raise ValueError("Source and graph events differ")
    if "replay_all_voltage_range_mv" in metadata:
        _validate_voltage_range(metadata["replay_all_voltage_range_mv"])
    if metadata["acquisition_settings"] is not None:
        for field in ("filtered_total_uv", "valid_samples", "saturated_samples"):
            if arrays[field].shape != time.shape or not np.isfinite(arrays[field]).all():
                raise ValueError("Invalid acquisition output")
        if (
            arrays["valid_samples"].dtype != np.bool_
            or arrays["saturated_samples"].dtype != np.bool_
        ):
            raise ValueError("Invalid acquisition mask")
        _verify_acquisition(
            arrays, metadata["acquisition_settings"], metadata["configuration"].get("acquisition")
        )
    return {
        "manifest": manifest,
        "metadata": metadata,
        "arrays": arrays,
        "evidence": evidence,
        "graph_binary": payloads["graph.bin"],
    }
