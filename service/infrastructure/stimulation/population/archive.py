"""Independent bounded verification of experimental fragment result artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import numpy as np

from service.application.population.contact_preflight import fragment_contact_receipt
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.domain.target_response_limits import can_capture_targets, network_sample_ticks
from service.infrastructure.stimulation.population.diagnostics import fragment_edge_schedule
from service.infrastructure.stimulation.population.preview import (
    fragment_population_preview,
)
from service.infrastructure.stimulation.population.sparse_delta import (
    decode_sparse_delta,
    validate_sparse_snapshots,
)
from service.infrastructure.stimulation.population.target_response import (
    decode_target_response,
    encode_target_response_binary,
    expected_direct_targets,
)

MAX_FILE_BYTES = 256 * 1024 * 1024
LEGACY_FILES = (
    "signals.npz", "model.json", "source-provenance.jsonl", "fragment-population-preview.json"
)
FILES = (*LEGACY_FILES, "fragment-events.bin")
RESPONSE_FILES = (*FILES, 'fragment-response.npz')
BINARY_RESPONSE_FILES = (*RESPONSE_FILES, 'fragment-response.bin')
SPARSE_RESPONSE_FILES = (*BINARY_RESPONSE_FILES, 'fragment-delta.bin')
ARRAYS = {
    "time_ms",
    "neural_uv",
    "stimulus_artifact_uv",
    "total_uv",
    "stimulus_fraction",
    "spike_neurons",
    "spike_times_ms",
}


def _json(data):
    return json.loads(
        data,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Invalid JSON number: {value}")
        ),
    )


def load_verified_fragment_population(directory: Path, graph):
    """Verify file integrity and internal consistency; do not assert biological validity."""
    root = directory.resolve()
    manifest_path = root / "manifest.json"
    if (
        manifest_path.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.stat().st_size > 65536
    ):
        raise ValueError("Invalid fragment manifest")
    manifest = _json(manifest_path.read_bytes())
    if (
        not isinstance(manifest, dict)
        or manifest.get("kind") != "experimental-fragment-population"
        or manifest.get("graph_sha256") != graph.provenance.get("manifest_sha256")
        or not isinstance(manifest.get("files"), list)
        or [row.get("name") if isinstance(row, dict) else None for row in manifest["files"]]
        not in (list(SPARSE_RESPONSE_FILES), list(BINARY_RESPONSE_FILES), list(RESPONSE_FILES),
                list(FILES), list(LEGACY_FILES))
    ):
        raise ValueError("Fragment manifest does not match graph")
    contents = {}
    for row in manifest["files"]:
        path = root / row["name"]
        if (
            set(row) != {"name", "bytes", "sha256"}
            or path.is_symlink()
            or not path.is_file()
            or type(row["bytes"]) is not int
            or not 0 < row["bytes"] <= MAX_FILE_BYTES
            or path.stat().st_size != row["bytes"]
            or not isinstance(row["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
        ):
            raise ValueError("Invalid fragment artifact metadata")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Fragment artifact checksum mismatch")
        if row["name"] != "signals.npz":
            contents[row["name"]] = data
    metadata = _json(contents["model.json"])
    if not isinstance(metadata, dict):
        raise ValueError("Invalid fragment model metadata")
    config = FragmentPopulationConfig.model_validate(metadata.get("configuration"))
    if (
        config.digest() != manifest.get("configuration_sha256")
        or metadata.get("configuration_sha256") != config.digest()
        or config.graph_manifest_sha256 != manifest["graph_sha256"]
        or metadata.get("source_ids") != config.source_ids
        or metadata.get("coverage") != manifest.get("coverage")
        or metadata.get("interpretation") != manifest.get("interpretation")
    ):
        raise ValueError("Fragment configuration mismatch")
    receipt = metadata.get("contact_screen")
    if receipt is not None:
        if (not isinstance(receipt, dict) or type(receipt.get("potential_intersections")) is not int
                or receipt["potential_intersections"] != 0):
            raise ValueError("Invalid contact-screen receipt")
        expected_receipt = fragment_contact_receipt(
            config, graph, {"indexed": receipt.get("indexed"),
                            "examined": receipt.get("examined"),
                            "potential_intersections": [],
                            "index_sha256": receipt.get("index_sha256")},
            allow_legacy="index_sha256" not in receipt,
        )
        if receipt != expected_receipt:
            raise ValueError("Contact-screen receipt does not match configuration")
    diagnostics, schedules = metadata.get("diagnostics"), metadata.get("schedules")
    if (
        not isinstance(diagnostics, list)
        or len(diagnostics) != len(config.source_ids)
        or any(not isinstance(row, dict) for row in diagnostics)
        or [row.get("body_id") for row in diagnostics] != list(map(str, config.source_ids))
    ):
        raise ValueError("Incomplete fragment diagnostics")
    expected = [
        fragment_edge_schedule(
            row,
            max_distance_um=config.max_distance_um,
            duration_ms=int(config.simulation.duration_ms),
            allow_partial_geometry=config.allow_partial_geometry is True,
        )
        for row in diagnostics
    ]
    if (
        expected != schedules
        or any(
            row["graph_sha256"] != manifest["graph_sha256"]
            or row["threshold_mv"] != config.threshold_mv
            for row in expected
        )
        or len({row["simulation_sha256"] for row in expected}) != 1
    ):
        raise ValueError("Fragment schedule mismatch")
    response_metadata = metadata.get('target_response')
    response_arrays = None
    if response_metadata is not None:
        scope = response_metadata.get('scope') if isinstance(response_metadata, dict) else None
        if scope not in (None, 'network-excluding-forced-sources'):
            raise ValueError('Unknown target response scope')
        network_ids = graph.ids if scope else None
        excluded = set(config.source_ids)
        targets = ([int(body) for body in network_ids if int(body) not in excluded]
                   if scope else expected_direct_targets(schedules, config.source_ids))
        policy = (response_metadata.get('limit_policy')
                  if isinstance(response_metadata, dict) else None)
        if policy not in (None, 'samples-4000000-v1'):
            raise ValueError('Unknown target response limit policy')
        duration = int(config.simulation.duration_ms)
        ticks = network_sample_ticks(len(targets), duration) if scope else None
        acceptable = (ticks is not None if scope else
                      can_capture_targets(len(targets), duration) if policy else
                      0 < len(targets) <= 4096)
        status = ('no_direct_targets' if not targets else 'recorded' if acceptable
                  else 'target_limit_exceeded')
        expected_response = {'status': status, 'target_count': len(targets),
                             'graph_sha256': config.graph_manifest_sha256,
                             'configuration_sha256': config.digest(), 'seed': config.seed}
        if policy:
            expected_response['limit_policy'] = policy
        if scope:
            if not policy:
                raise ValueError('Network response requires a limit policy')
            expected_response['scope'] = scope
            if ticks is not None and len(ticks) != duration + 1:
                expected_response['sample_times_ms'] = ticks
        if status == 'recorded':
            expected_response['format'] = ('paired-lif-network-v3' if scope
                                           and len(ticks) != duration + 1
                                           else 'paired-lif-network-v2' if scope
                                           else 'paired-lif-targets-v1')
        if response_metadata != expected_response:
            raise ValueError('Target response metadata mismatch')
        if status == 'recorded':
            if 'fragment-response.npz' not in contents:
                raise ValueError('Target response artifact is missing')
            response_arrays = decode_target_response(
                contents['fragment-response.npz'], schedules=schedules,
                source_ids=config.source_ids, duration_ms=int(config.simulation.duration_ms),
                network_ids=network_ids,
            )
            if 'fragment-response.bin' in contents:
                expected_binary = encode_target_response_binary(
                    response_arrays, schedules=schedules, source_ids=config.source_ids,
                    duration_ms=int(config.simulation.duration_ms),
                    graph_sha256=config.graph_manifest_sha256, configuration_sha256=config.digest(),
                    network_ids=network_ids,
                )
                if contents['fragment-response.bin'] != expected_binary:
                    raise ValueError('Target response binary does not match archive')
        elif 'fragment-response.npz' in contents:
            raise ValueError('Unexpected target response artifact')
    elif 'fragment-response.npz' in contents:
        raise ValueError('Target response metadata is missing')
    sparse_meta = metadata.get('sparse_delta')
    if sparse_meta is not None:
        if not isinstance(sparse_meta, dict) or sparse_meta.get('status') not in (
                'recorded', 'limit_exceeded'):
            raise ValueError('Invalid sparse metadata')
        expected_sparse = {'status': sparse_meta['status'],
                           'graph_sha256': config.graph_manifest_sha256,
                           'configuration_sha256': config.digest()}
        if sparse_meta['status'] == 'recorded':
            if 'fragment-delta.bin' not in contents or response_arrays is None or not scope:
                raise ValueError('Sparse artifact or network snapshots missing')
            sparse = decode_sparse_delta(contents['fragment-delta.bin'], graph=graph,
                source_ids=config.source_ids, duration_ms=int(config.simulation.duration_ms),
                configuration_sha256=config.digest())
            validate_sparse_snapshots(sparse, response_arrays, graph)
            expected_sparse.update({'format': 'sparse-lif-delta-v1',
                                    'entries': len(sparse['values'])})
        elif 'fragment-delta.bin' in contents:
            raise ValueError('Unexpected sparse artifact')
        if sparse_meta != expected_sparse:
            raise ValueError('Sparse metadata mismatch')
    elif 'fragment-delta.bin' in contents:
        raise ValueError('Sparse metadata is missing')
    proofs_raw = contents["source-provenance.jsonl"]
    try:
        proofs = [_json(line) for line in proofs_raw.splitlines()]
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid fragment source provenance") from exc
    recording = metadata.get("recording")
    if (
        not isinstance(recording, dict)
        or recording.get("cells") != len(config.source_ids)
        or recording.get("cell_provenance_sha256") != hashlib.sha256(proofs_raw).hexdigest()
        or recording.get("cell_provenance_exported") is not True
        or recording.get("cell_provenance_fields_present") is not True
        or len(proofs) != len(diagnostics)
    ):
        raise ValueError("Incomplete fragment source provenance")
    simulation = config.model_dump(mode="json")["simulation"]
    requested = {
        k: v
        for k, v in simulation.items()
        if k not in {"electrode_um", "reference_um", "coordinate_frame", "source_model"}
    }
    identity = hashlib.sha256()
    for proof, row in zip(proofs, diagnostics, strict=True):
        if (
            not isinstance(proof, dict)
            or proof.get("body_id") != row["body_id"]
            or proof.get("morphology_sha256") != row.get("morphology_sha256")
            or type(proof.get("components")) is not int
            or proof["components"] != row.get("components")
            or not isinstance(proof.get("configuration"), dict)
        ):
            raise ValueError("Fragment source provenance mismatch")
        proof_config = proof["configuration"]
        digest = hashlib.sha256(
            json.dumps(proof_config, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
                "utf8"
            )
        ).hexdigest()
        if digest != row["simulation_sha256"] or any(
            proof_config.get(k) != v for k, v in requested.items()
        ):
            raise ValueError("Fragment source configuration mismatch")
        identity.update(f"{row['body_id']}:{row['morphology_sha256']}\n".encode("ascii"))
    if (
        recording.get("ordered_sources_sha256") != identity.hexdigest()
        or recording.get("electrode_um") != list(config.simulation.electrode_um)
        or recording.get("reference_um") != list(config.simulation.reference_um)
        or recording.get("source_model") != config.simulation.source_model
    ):
        raise ValueError("Fragment recording provenance mismatch")
    archive_path = root / "signals.npz"
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if (
            {entry.filename for entry in members} != {name + ".npy" for name in ARRAYS}
            or len(members) != len(ARRAYS)
            or sum(entry.file_size for entry in members) > MAX_FILE_BYTES
        ):
            raise ValueError("Invalid or oversized fragment signal archive")
    with np.load(archive_path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in ARRAYS}
    time, neurons, ticks = arrays["time_ms"], arrays["spike_neurons"], arrays["spike_times_ms"]
    traces = [
        arrays[name]
        for name in ("neural_uv", "stimulus_artifact_uv", "total_uv", "stimulus_fraction")
    ]
    positions = np.searchsorted(graph.ids, config.source_ids)
    if (
        any(
            pos >= graph.size or int(graph.ids[pos]) != body
            for pos, body in zip(positions, config.source_ids, strict=True)
        )
        or time.ndim != 1
        or len(time) < 2
        or not np.isfinite(time).all()
        or time[0] != 0
        or np.any(np.diff(time) <= 0)
        or abs(time[-1] - config.simulation.duration_ms) > 1e-9
        or any(value.shape != time.shape or not np.isfinite(value).all() for value in traces)
        or np.any(np.abs(arrays["stimulus_fraction"]) > 1.0 + 1e-9)
        or not np.allclose(
            arrays["total_uv"],
            arrays["neural_uv"] + arrays["stimulus_artifact_uv"],
            rtol=1e-12,
            atol=1e-12,
        )
        or neurons.ndim != 1
        or neurons.dtype.kind not in "iu"
        or ticks.shape != neurons.shape
        or not np.isfinite(ticks).all()
        or np.any(neurons < 0)
        or np.any(neurons >= graph.size)
        or np.any(ticks < 1)
        or np.any(ticks > config.simulation.duration_ms)
        or np.any(ticks[1:] < ticks[:-1])
        or np.isin(neurons, positions).any()
    ):
        raise ValueError("Invalid fragment recording or network output")
    preview = _json(contents["fragment-population-preview.json"])
    expected_preview = fragment_population_preview(
        arrays,
        source_count=len(config.source_ids),
        duration_ms=int(config.simulation.duration_ms),
        edge_event_count=sum(
            event["count"] for schedule in schedules for event in schedule["edge_events"]
        ),
        unresolved_graph_pairs=(sum(len(schedule.get("unresolved_geometry", []))
                                    for schedule in schedules)
                                if config.allow_partial_geometry is True else None),
    )
    if preview != expected_preview:
        raise ValueError("Fragment preview does not match recording")
    if "fragment-events.bin" in contents:
        expected_events = (np.asarray(graph.ids, dtype="<u8").tobytes()
                           + np.asarray(neurons, dtype="<i4").tobytes()
                           + np.asarray(ticks, dtype="<f4").tobytes())
        if (metadata.get("events") != {"format": "fragment-events-v1",
                                      "graph_sha256": config.graph_manifest_sha256,
                                      "node_count": graph.size, "event_count": len(neurons)}
                or contents["fragment-events.bin"] != expected_events):
            raise ValueError("Fragment event journal does not match recording")
    elif metadata.get("events") is not None:
        raise ValueError("Fragment event journal is missing")
    return {
        "manifest": manifest,
        "metadata": metadata,
        "arrays": arrays,
        "preview": preview,
        "target_response": response_arrays,
        "interpretation": "integrity and internal consistency checked; no biological validation",
    }
