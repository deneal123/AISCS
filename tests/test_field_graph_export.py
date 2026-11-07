import hashlib
import json

import numpy as np
import pytest

from service.infrastructure.connectome.forced_export import encode_forced_spikes
from service.infrastructure.connectome.forced_network import run_forced_network
from service.infrastructure.stimulation.acquisition import acquire_channel
from service.infrastructure.stimulation.field_graph_export import (
    export_field_graph_replay,
    load_verified_field_graph_replay,
)
from service.infrastructure.stimulation.threshold_diagnostics import (
    compartment_crossing_events,
    compartment_crossing_summary,
)
from tests.test_forced_network import graph


def example():
    model = graph()
    network = run_forced_network(
        model, seed=1, duration_ms=6, forced_cell_ids=[10], events={10: [1]}
    )
    _, description, digest = encode_forced_spikes(model, network)
    provenance = b'{"body_id":"20"}\n'
    evidence = (
        json.dumps(
            {
                "mapping": {"body_id": "20"},
                "provenance": {"body_id": "20"},
                "connectome_sha256": digest,
            }
        )
        + "\n"
    ).encode()
    time = np.arange(7.0)
    selection = {"body_id": 10, "child_node_id": 2, "threshold_mv": -20}
    source = {
        "network": network,
        "recording": {"neural_uv": np.full(7, 0.4)},
        "sources": [
            {
                "selection": selection,
                "sampling": {},
                "provenance": {},
                "time_ms": time,
                "voltage_mv": np.array([-65, -10, -65, -65, -65, -65, -65]),
                "event_ticks_ms": np.array([1]),
            }
        ],
    }
    recording = {
        "time_ms": time,
        "neural_uv": np.ones(7),
        "stimulus_artifact_uv": 2 * np.ones(7),
        "stimulus_fraction": np.ones(7),
        "total_uv": 3 * np.ones(7),
        "graph_stream_sha256": digest,
    }
    replay = {
        "neural_uv": np.full(7, 0.6),
        "replay_evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "cell_provenance_sha256": hashlib.sha256(provenance).hexdigest(),
        "replay_evidence_exported": True,
        "cell_provenance_exported": True,
        "source_sha256": digest,
    }
    result = {
        "source": source,
        "recording": recording,
        "replay": replay,
        "configuration": {"replay_ids": [20], "source_cells": [selection]},
        "graph_description": description,
        "acquisition": None,
        "interpretation": "one-way",
    }
    return model, result, evidence, provenance


def test_export_hashes_all_files_and_does_not_overwrite(tmp_path):
    model, result, evidence, provenance = example()
    target = tmp_path / "result"
    manifest = export_field_graph_replay(
        result, model, target, evidence=evidence, provenance=provenance
    )
    assert len(manifest["files"]) == 5
    for item in manifest["files"]:
        raw = (target / item["name"]).read_bytes()
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
    assert json.loads((target / "manifest.json").read_text()) == manifest
    with np.load(target / "signals.npz", allow_pickle=False) as signals:
        np.testing.assert_array_equal(signals["total_uv"], 3 * np.ones(7))
        np.testing.assert_array_equal(signals["source_0_event_ticks_ms"], [1])
    verified = load_verified_field_graph_replay(target, model)
    assert verified["metadata"]["configuration"]["replay_ids"] == [20]
    with pytest.raises(FileExistsError):
        export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)


def test_export_rejects_changed_evidence_before_creating_directory(tmp_path):
    model, result, evidence, provenance = example()
    with pytest.raises(ValueError, match="digest"):
        export_field_graph_replay(
            result, model, tmp_path / "result", evidence=evidence + b" ", provenance=provenance
        )
    assert not (tmp_path / "result").exists()


def test_source_morphology_selection_digest_is_checked_and_preserved(tmp_path):
    model, result, evidence, provenance = example()
    selection = result['source']['sources'][0]['selection']
    selection['morphology_sha256'] = 'a' * 64
    result['source']['sources'][0]['provenance']['morphology_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='Source morphology digest mismatch'):
        export_field_graph_replay(
            result, model, tmp_path / 'bad', evidence=evidence, provenance=provenance
        )
    result['source']['sources'][0]['provenance']['morphology_sha256'] = 'a' * 64
    target = tmp_path / 'good'
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    verified = load_verified_field_graph_replay(target, model)
    assert verified['metadata']['source_cells'][0]['provenance']['morphology_sha256'] == 'a' * 64


def test_compartment_diagnostic_survives_export_and_selected_trace_is_checked(tmp_path):
    model, result, evidence, provenance = example()
    cell = result['source']['sources'][0]
    all_voltage = np.stack([cell['voltage_mv'], np.full(7, -65.)])
    diagnostic = compartment_crossing_summary(cell['time_ms'], all_voltage,
                                               selected_index=0, threshold_mv=-20.)
    cell['provenance'] = {'vertices': 3, 'components': 1}
    cell['sampling'] = {'nseg_per_edge': 1, 'result_segment_index': 0}
    cell['crossing_diagnostics'] = diagnostic
    target = tmp_path / 'good'
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    verified = load_verified_field_graph_replay(target, model)
    assert verified['metadata']['source_cells'][0]['crossing_diagnostics'] == diagnostic
    cell['crossing_diagnostics'] = {**diagnostic, 'selected_crossings': 0}
    with pytest.raises(ValueError, match='Inconsistent compartment crossing'):
        export_field_graph_replay(result, model, tmp_path / 'bad',
                                  evidence=evidence, provenance=provenance)
    cell['crossing_diagnostics'] = {**diagnostic, 'compartments': 3}
    with pytest.raises(ValueError, match='do not match morphology'):
        export_field_graph_replay(result, model, tmp_path / 'wrong-size',
                                  evidence=evidence, provenance=provenance)


def test_optional_compartment_crossings_are_verified_and_round_trip(tmp_path):
    model, result, evidence, provenance = example()
    cell = result['source']['sources'][0]
    time, selected = cell['time_ms'], cell['voltage_mv']
    all_voltage = np.stack([selected, [-65., -65., -10., -65., -65., -65., -65.]])
    positions = np.array([[1., 2., 3.], [4., 5., 6.]])
    cell['sampling'] = {'result_segment_index': 0}
    cell['crossing_diagnostics'] = compartment_crossing_summary(
        time, all_voltage, selected_index=0, threshold_mv=-20.)
    cell['compartment_crossings'] = compartment_crossing_events(
        time, all_voltage, positions, threshold_mv=-20.)
    result['configuration']['retain_compartment_crossings'] = True
    target = tmp_path / 'good'
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    verified = load_verified_field_graph_replay(target, model)
    assert verified['metadata']['source_cells'][0]['compartment_crossings']['events'] == 2
    np.testing.assert_array_equal(verified['arrays']['source_0_crossing_sample_indices'], [1, 2])
    np.testing.assert_array_equal(verified['arrays']['source_0_crossing_midpoints_um'], positions)
    from service.infrastructure.stimulation.field_graph_preview import field_graph_preview

    preview = field_graph_preview(target, model)
    assert preview['compartment_events']['total'] == 2
    assert preview['compartment_events']['events'] == [
        ['10', 1., 0, 1., 2., 3.], ['10', 2., 1, 4., 5., 6.]
    ]
    assert preview['compartment_bin_coverage'] == {
        'sources_checked': 1, 'sources_with_unrepresented_bins': 1,
        'unrepresented_source_bins': 1,
    }
    cell['compartment_crossings']['sample_indices'][0] = 3
    with pytest.raises(ValueError, match='contradicts diagnostics'):
        export_field_graph_replay(result, model, tmp_path / 'bad',
                                  evidence=evidence, provenance=provenance)


def test_export_rejects_changed_graph_and_invalid_trace(tmp_path):
    model, result, evidence, provenance = example()
    result["recording"]["graph_stream_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Graph event"):
        export_field_graph_replay(
            result, model, tmp_path / "wrong", evidence=evidence, provenance=provenance
        )
    result["recording"]["graph_stream_sha256"] = result["replay"]["source_sha256"]
    result["recording"]["total_uv"][0] = 999
    with pytest.raises(ValueError, match="signal"):
        export_field_graph_replay(
            result, model, tmp_path / "bad", evidence=evidence, provenance=provenance
        )


def test_loader_rejects_altered_signal_file(tmp_path):
    model, result, evidence, provenance = example()
    target = tmp_path / "result"
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    with (target / "signals.npz").open("ab") as output:
        output.write(b"altered")
    with pytest.raises(ValueError, match="checksum"):
        load_verified_field_graph_replay(target, model)


def test_loader_rejects_duplicate_or_unpaired_archive_manifest(tmp_path):
    model, result, evidence, provenance = example()
    target = tmp_path / "result"
    manifest = export_field_graph_replay(
        result, model, target, evidence=evidence, provenance=provenance
    )
    path = target / "manifest.json"
    manifest["files"].append(manifest["files"][0].copy())
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        load_verified_field_graph_replay(target, model)
    manifest["files"].pop()
    manifest["current_manifest_sha256"] = "a" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest"):
        load_verified_field_graph_replay(target, model)


def test_loader_verifies_streamed_archive_checksum(tmp_path):
    model, result, evidence, provenance = example()
    target = tmp_path / "result"
    manifest = export_field_graph_replay(
        result, model, target, evidence=evidence, provenance=provenance
    )
    for name, data in (("field-graph-preview.json", b"{}"), ("currents.zip", b"archive")):
        (target / name).write_bytes(data)
        manifest["files"].append({"name": name, "bytes": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
    manifest["current_manifest_sha256"] = "a" * 64
    (target / "manifest.json").write_text(json.dumps(manifest))
    load_verified_field_graph_replay(target, model)
    (target / "currents.zip").write_bytes(b"altered")
    with pytest.raises(ValueError, match="checksum"):
        load_verified_field_graph_replay(target, model)


def test_loader_rejects_wrong_sampling_location_even_if_rehashed(tmp_path):
    model, result, evidence, provenance = example()
    result['source']['sources'][0]['selection']['sampling_fraction'] = .9
    result['source']['sources'][0]['sampling'] = {
        'requested_edge_fraction': .9, 'edge_fraction': 5 / 6,
        'nseg_per_edge': 3, 'result_segment_index': 2,
    }
    result['configuration']['simulation_parameters'] = {'nseg_per_edge': 3}
    target = tmp_path / 'result'
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    load_verified_field_graph_replay(target, model)
    metadata_path = target / 'metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata['source_cells'][0]['sampling']['edge_fraction'] = .5
    metadata_path.write_text(json.dumps(metadata))
    manifest_path = target / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    entry = next(item for item in manifest['files'] if item['name'] == 'metadata.json')
    raw = metadata_path.read_bytes()
    entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Source sampling location mismatch'):
        load_verified_field_graph_replay(target, model)


def test_loader_checks_source_events_even_if_manifest_hash_is_updated(tmp_path):
    model, result, evidence, provenance = example()
    target = tmp_path / "result"
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    signal_path = target / "signals.npz"
    with np.load(signal_path, allow_pickle=False) as loaded:
        arrays = {key: loaded[key] for key in loaded.files}
    arrays["source_0_event_ticks_ms"] = np.array([2])
    with signal_path.open("wb") as output:
        np.savez_compressed(output, **arrays)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(item for item in manifest["files"] if item["name"] == "signals.npz")
    raw = signal_path.read_bytes()
    entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Source voltage and event times differ"):
        load_verified_field_graph_replay(target, model)


def test_loader_recalculates_acquisition_mask_after_hash_update(tmp_path):
    model, result, evidence, provenance = example()
    data = result["recording"]
    settings = {"low_hz": 10, "high_hz": 200, "recovery_ms": 0, "clip_uv": 2}
    result["configuration"]["acquisition"] = settings
    result["acquisition"] = acquire_channel(
        data["time_ms"],
        data["neural_uv"],
        data["stimulus_artifact_uv"],
        data["stimulus_fraction"],
        **settings,
    )
    target = tmp_path / "result"
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    signal_path = target / "signals.npz"
    with np.load(signal_path, allow_pickle=False) as loaded:
        arrays = {key: loaded[key] for key in loaded.files}
    arrays["valid_samples"][0] = True
    with signal_path.open("wb") as output:
        np.savez_compressed(output, **arrays)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    entry = next(item for item in manifest["files"] if item["name"] == "signals.npz")
    raw = signal_path.read_bytes()
    entry.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Acquisition mask"):
        load_verified_field_graph_replay(target, model)
