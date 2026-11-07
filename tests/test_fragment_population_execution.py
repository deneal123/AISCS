import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.population.fragment_contact_preflight import fragment_contact_receipt
from service.application.population.fragment_population_execution import FragmentPopulationExecution
from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from service.infrastructure.stimulation.fragment_output_diagnostics import fragment_edge_schedule
from service.infrastructure.stimulation.fragment_population_archive import (
    load_verified_fragment_population,
)
from tests.test_fragment_population_contract import example


@pytest.mark.parametrize('partial', [False, True])
def test_experimental_execution_exports_complete_checked_subset(tmp_path, monkeypatch, partial):
    config = FragmentPopulationConfig.model_validate(
        {**example(), **({'allow_partial_geometry': True} if partial else {})})
    graph = SimpleNamespace(
        size=4,
        ids=np.array([10, 20, 30, 40]),
        provenance={"manifest_sha256": config.graph_manifest_sha256},
    )
    settings = config.model_dump(mode="json")["simulation"]
    settings = {
        k: v
        for k, v in settings.items()
        if k not in {"electrode_um", "reference_um", "coordinate_frame", "source_model"}
    }
    simulation_sha = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    proof = b"".join(
        (
            json.dumps(
                {
                    "body_id": str(body),
                    "morphology_sha256": "d" * 64,
                    "components": 1,
                    "configuration": settings,
                }
            )
            + "\n"
        ).encode()
        for body in (10, 20)
    )
    ordered_sha = hashlib.sha256(
        ("10:" + "d" * 64 + "\n20:" + "d" * 64 + "\n").encode()
    ).hexdigest()
    diagnostics = [
        {
            "body_id": str(body),
            "graph_sha256": config.graph_manifest_sha256,
            "simulation_sha256": simulation_sha,
            "morphology_sha256": "d" * 64,
            "components": 1,
            "threshold_mv": -20.0,
            "duration_ms": 10,
            "source_pairs": 0,
            "graph_pairs": 0,
            "candidates": [],
        }
        for body in (10, 20)
    ]
    if partial:
        diagnostics[0]['candidates'] = [{'included_in_graph': True, 'partner_id': '30',
            'centerline_distance_um': 2.1, 'source_position_8nm': [1, 2, 3],
            'status': 'geometry_unresolved', 'stimulated_ticks_ms': None, 'control_ticks_ms': None}]
        diagnostics[0]['source_pairs'] = diagnostics[0]['graph_pairs'] = 1
    schedules = [
        fragment_edge_schedule(item, max_distance_um=2.0, duration_ms=10,
                               allow_partial_geometry=partial) for item in diagnostics
    ]

    def run(_graph, _index, _dirs, *, provenance_sink, **_kwargs):
        provenance_sink.write(proof)
        return {
            "recording": {
                "time_ms": np.array([0.0, 10.0]),
                "neural_uv": np.array([1.0, 2.0]),
                "stimulus_artifact_uv": np.array([3.0, 4.0]),
                "total_uv": np.array([4.0, 6.0]),
                "stimulus_fraction": np.array([0.0, 0.0]),
                "cells": 2,
                "cell_provenance_exported": True,
                "cell_provenance_fields_present": True,
                "cell_provenance_sha256": hashlib.sha256(proof).hexdigest(),
                "ordered_sources_sha256": ordered_sha,
                "electrode_um": [0.0, 50.0, 0.0],
                "reference_um": [100.0, 50.0, 0.0],
                "source_model": "pointsource",
            },
            "network": {
                "network": {"spike_neurons": np.array([2]), "spike_times_ms": np.array([3.0])},
                "source_ids": [10, 20],
                "schedules": schedules,
            },
            "diagnostics": diagnostics,
            "coverage": "explicit subset",
            "interpretation": "uncalibrated model",
        }

    monkeypatch.setattr(
        "service.application.population.fragment_population_execution.run_fragment_population", run
    )
    receipt = fragment_contact_receipt(
        config,
        graph,
        {
            "indexed": 4,
            "examined": 2,
            "potential_intersections": [],
            "index_sha256": {"bounds": "a" * 64, "radii": "b" * 64, "segments": "c" * 64},
        },
    )
    manifest = FragmentPopulationExecution(graph, None, []).execute(
        config, tmp_path, contact_receipt=receipt
    )
    assert manifest["kind"] == "experimental-fragment-population"
    assert len(manifest["files"]) == 5
    with np.load(tmp_path / "signals.npz", allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["stimulus_fraction"], [0.0, 0.0])
    for file in manifest["files"]:
        assert hashlib.sha256((tmp_path / file["name"]).read_bytes()).hexdigest() == file["sha256"]
    checked = load_verified_fragment_population(tmp_path, graph)
    assert checked["metadata"]["source_ids"] == [10, 20]
    assert checked["metadata"]["contact_screen"] == receipt
    if partial:
        assert checked['preview']['unresolved_graph_pairs'] == 1
        assert 'события неизвестны' in checked['preview']['limitations'][-1]
        assert checked['metadata']['schedules'][0]['edge_events'] == []
        model_path = tmp_path / 'model.json'
        manifest_path = tmp_path / 'manifest.json'
        original_model, original_manifest = model_path.read_bytes(), manifest_path.read_bytes()
        changed = json.loads(original_model)
        changed['diagnostics'][0]['candidates'][0]['stimulated_ticks_ms'] = [1]
        altered_model = json.dumps(changed).encode()
        model_path.write_bytes(altered_model)
        altered_manifest = json.loads(original_manifest)
        model_entry = next(row for row in altered_manifest['files'] if row['name'] == 'model.json')
        model_entry.update({'bytes': len(altered_model),
                            'sha256': hashlib.sha256(altered_model).hexdigest()})
        manifest_path.write_text(json.dumps(altered_manifest), encoding='utf8')
        with pytest.raises(ValueError, match='cannot have observed events'):
            load_verified_fragment_population(tmp_path, graph)
        model_path.write_bytes(original_model)
        manifest_path.write_bytes(original_manifest)

    def run_network(*args, **kwargs):
        from service.domain.target_response_limits import network_sample_ticks

        result = run(*args, **kwargs)
        ticks = network_sample_ticks(2, 10)
        active = np.zeros((len(ticks), 2), dtype=np.float32)
        active[1:, 1] = 0.25
        result['network']['target_response'] = {
            'status': 'recorded', 'target_count': 2,
            'scope': 'network-excluding-forced-sources',
            'target_ids': [30, 40], 'time_ms': np.asarray(ticks, dtype=np.float32),
            'active_relative_mv': active, 'control_relative_mv': np.zeros_like(active),
            'delta_relative_mv': active,
        }
        result['network']['network']['sparse_delta'] = {
            'status': 'recorded', 'offsets': np.asarray([0, 0, *range(1, 11)], dtype=np.uint32),
            'indices': np.full(10, 3, dtype=np.int32), 'values': np.full(10, .25, dtype=np.float32),
        }
        return result

    monkeypatch.setattr(
        'service.application.population.fragment_population_execution.run_fragment_population', run_network
    )
    network_path = tmp_path / 'network'
    network_manifest = FragmentPopulationExecution(graph, None, []).execute(
        config, network_path, contact_receipt=receipt
    )
    assert len(network_manifest['files']) == 8
    network_result = load_verified_fragment_population(network_path, graph)
    assert network_result['metadata']['target_response']['format'] == 'paired-lif-network-v2'
    assert (network_path / 'fragment-response.bin').read_bytes()[:4] == b'FRS2'
    assert (network_path / 'fragment-delta.bin').read_bytes()[:4] == b'SPD1'
    np.testing.assert_array_equal(network_result['target_response']['target_ids'], [30, 40])
    # Limit only snapshot density here; the sparse stream retains its own production bound.
    monkeypatch.setattr('service.domain.target_response_limits.MAX_TARGET_RESPONSE_VALUES', 6)
    sampled_path = tmp_path / 'network-sampled'
    FragmentPopulationExecution(graph, None, []).execute(
        config, sampled_path, contact_receipt=receipt
    )
    sampled = load_verified_fragment_population(sampled_path, graph)
    assert sampled['metadata']['target_response']['format'] == 'paired-lif-network-v3'
    assert sampled['metadata']['target_response']['sample_times_ms'] == [0, 5, 10]
    assert (sampled_path / 'fragment-response.bin').read_bytes()[:4] == b'FRS3'
    events_path = tmp_path / "fragment-events.bin"
    original_events = events_path.read_bytes()
    corrupted_events = bytearray(original_events)
    corrupted_events[0] ^= 1
    events_path.write_bytes(corrupted_events)
    manifest_path = tmp_path / "manifest.json"
    altered_manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    event_entry = next(
        item for item in altered_manifest["files"] if item["name"] == events_path.name
    )
    event_entry["sha256"] = hashlib.sha256(corrupted_events).hexdigest()
    manifest_path.write_text(json.dumps(altered_manifest), encoding="utf8")
    with pytest.raises(ValueError, match="event journal"):
        load_verified_fragment_population(tmp_path, graph)
    events_path.write_bytes(original_events)
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    legacy = fragment_contact_receipt(
        config,
        graph,
        {"indexed": 4, "examined": 2, "potential_intersections": []},
        allow_legacy=True,
    )
    assert "index_sha256" not in legacy
    with pytest.raises(ValueError, match="index hashes"):
        fragment_contact_receipt(
            config, graph, {"indexed": 4, "examined": 2, "potential_intersections": []}
        )
    model_path = tmp_path / "model.json"
    original_model = model_path.read_bytes()
    legacy_model = json.loads(original_model)
    legacy_model["contact_screen"] = legacy
    model_path.write_text(json.dumps(legacy_model), encoding="utf8")
    legacy_manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    legacy_entry = next(item for item in legacy_manifest["files"] if item["name"] == "model.json")
    legacy_entry["bytes"] = model_path.stat().st_size
    legacy_entry["sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(legacy_manifest), encoding="utf8")
    assert (
        load_verified_fragment_population(tmp_path, graph)["metadata"]["contact_screen"] == legacy
    )
    model_path.write_bytes(original_model)
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    altered_model = json.loads(original_model)
    altered_model["contact_screen"]["contacts_um"][0][0] += 1
    model_path.write_text(json.dumps(altered_model), encoding="utf8")
    altered_manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    model_entry = next(item for item in altered_manifest["files"] if item["name"] == "model.json")
    model_entry["bytes"] = model_path.stat().st_size
    model_entry["sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(altered_manifest), encoding="utf8")
    with pytest.raises(ValueError, match="Contact-screen receipt"):
        load_verified_fragment_population(tmp_path, graph)
    model_path.write_bytes(original_model)
    manifest_path.write_text(json.dumps(manifest), encoding="utf8")
    with pytest.raises(FileExistsError):
        FragmentPopulationExecution(graph, None, []).execute(config, tmp_path)
    with pytest.raises(ValueError, match="graph"):
        FragmentPopulationExecution(
            SimpleNamespace(provenance={"manifest_sha256": "b" * 64}), None, []
        ).execute(config, tmp_path / "other")
    # Rehashing a modified provenance file must not bypass the model-level binding.
    proof_path = tmp_path / "source-provenance.jsonl"
    modified = proof_path.read_bytes().replace(b'"body_id": "10"', b'"body_id": "11"')
    assert modified != proof_path.read_bytes()
    proof_path.write_bytes(modified)
    manifest_path = tmp_path / "manifest.json"
    altered = json.loads(manifest_path.read_text(encoding="utf8"))
    entry = next(item for item in altered["files"] if item["name"] == "source-provenance.jsonl")
    entry["sha256"] = hashlib.sha256(modified).hexdigest()
    manifest_path.write_text(json.dumps(altered), encoding="utf8")
    with pytest.raises(ValueError, match="provenance"):
        load_verified_fragment_population(tmp_path, graph)
    with (tmp_path / "model.json").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="metadata"):
        load_verified_fragment_population(tmp_path, graph)
