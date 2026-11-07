import copy

import pytest

from service.services.simulations.manifests.field_graph_manifest import (
    InvalidFieldGraphManifest,
    validate_field_graph_manifest,
    validate_field_graph_preview,
)


def manifest():
    names = [
        "graph.bin",
        "replay-evidence.jsonl",
        "replay-provenance.jsonl",
        "metadata.json",
        "signals.npz",
        "field-graph-preview.json",
    ]
    return {
        "format": "field-graph-replay-manifest-v1",
        "kind": "field-graph-replay",
        "configuration_sha256": "a" * 64,
        "files": [{"name": name, "bytes": 10, "sha256": "b" * 64} for name in names],
    }


def preview():
    return {
        "time_ms": [0.0, 1.0, 2.0],
        "neural_uv": [0.0, 1.0, 2.0],
        "total_uv": [0.0, 2.0, 3.0],
        "stimulus_fraction": [0.0, 1.0, 0.0],
        "samples": 3,
        "shown_samples": 3,
        "source_cells": 1,
        "replay_cells": 1,
        "network_spikes_by_ms": [0, 1, 0],
        "units": {"time_ms": "ms", "neural_uv": "µV", "total_uv": "µV"},
        "limitations": ["One-way and uncalibrated"],
        "acquisition": {
            "filtered_total_uv": [0.0, 1.0, 1.0],
            "valid_samples": [True, False, False],
            "saturated_samples": [False, True, False],
            "mask_scope": "conservative aggregation over the source bin",
            "settings": {"low_hz": 1, "high_hz": 100, "recovery_ms": 1, "clip_uv": 5},
            "mask_intervals": [
                {"start_ms": 0., "end_ms": 1., "valid": True, "saturated": False},
                {"start_ms": 1., "end_ms": 2., "valid": False, "saturated": True},
            ],
        },
    }


def configuration():
    return {
        "simulation": {"duration_ms": 2.0, "dt_ms": 1.0},
        "source_cells": [{"body_id": 10}],
        "replay_ids": [20],
        "acquisition": {"low_hz": 1, "high_hz": 100, "recovery_ms": 1, "clip_uv": 5},
    }


def test_accepts_manifest_and_preview():
    validate_field_graph_manifest(manifest(), configuration_sha256="a" * 64)
    validate_field_graph_preview(preview(), configuration())


def test_state_contrast_requires_complete_requested_artifact_group():
    value = manifest()
    names = ['state-contrast.bin', 'state-contrast.json', 'state-source-manifest.json']
    value['files'].extend({'name': name, 'bytes': 10, 'sha256': 'c' * 64} for name in names)
    validate_field_graph_manifest(value, configuration_sha256='a' * 64, retain_state_contrast=True)
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256='a' * 64,
                                      retain_state_contrast=False)
    value['files'].pop()
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256='a' * 64,
                                      retain_state_contrast=True)
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(manifest(), configuration_sha256='a' * 64,
                                      retain_state_contrast=True)


@pytest.mark.parametrize("voltage", [
    {"minimum": -17000., "maximum": -63.},
    None,
])
def test_voltage_range_is_optional_for_legacy_previews(voltage):
    value = preview()
    value["source_voltage_range_mv"] = voltage
    validate_field_graph_preview(value, configuration())


@pytest.mark.parametrize("voltage", [
    {"minimum": -1., "maximum": -2.}, {"minimum": True, "maximum": 1.},
    {"minimum": float("nan"), "maximum": 1.}, {"minimum": -1.},
])
def test_rejects_invalid_voltage_ranges(voltage):
    value = preview()
    value["source_voltage_range_mv"] = voltage
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())


def test_full_compartment_range_must_contain_selected_range():
    value = preview()
    value['source_voltage_range_mv'] = {'minimum': -70., 'maximum': -10.}
    value['source_all_compartments_voltage_range_mv'] = {'minimum': -500., 'maximum': 30.}
    validate_field_graph_preview(value, configuration())
    value['source_all_compartments_voltage_range_mv']['minimum'] = -60.
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())


@pytest.mark.parametrize("count", [True, -1, 2, 0.5])
def test_rejects_invalid_unobserved_threshold_count(count):
    value = preview()
    value["source_voltage_range_mv"] = {"minimum": -70., "maximum": -60.}
    value["source_all_compartments_voltage_range_mv"] = {"minimum": -70., "maximum": 30.}
    value["source_unobserved_threshold_candidates"] = count
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())


def test_unobserved_threshold_count_requires_full_range():
    value = preview()
    value["source_unobserved_threshold_candidates"] = 0
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())
    value["source_voltage_range_mv"] = {"minimum": -70., "maximum": -60.}
    value["source_all_compartments_voltage_range_mv"] = {"minimum": -70., "maximum": 30.}
    value["source_unobserved_threshold_candidates"] = 1
    validate_field_graph_preview(value, configuration())


def test_compartment_crossing_summary_has_bounded_counts():
    value = preview()
    value["source_compartment_crossings"] = {"sources_checked": 1, "outside_selected_only": 1,
                                              "earlier_than_selected": 0,
                                              "initial_above_sources": 1}
    validate_field_graph_preview(value, configuration())
    value["source_compartment_crossings"]["earlier_than_selected"] = 1
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())


def test_compartment_event_preview_requires_matching_source_and_sample_grid():
    value, config = preview(), configuration()
    config['retain_compartment_crossings'] = True
    value['compartment_events'] = {'total': 1, 'shown': 1,
        'selection': 'uniform rank sample ordered by time, body and compartment',
        'events': [[str(config['source_cells'][0]['body_id']), 1., 0, 1., 2., 3.]]}
    value['compartment_bin_coverage'] = {'sources_checked': 1,
        'sources_with_unrepresented_bins': 1, 'unrepresented_source_bins': 1}
    validate_field_graph_preview(value, config)
    value['compartment_bin_coverage']['unrepresented_source_bins'] = 0
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, config)
    value['compartment_bin_coverage']['unrepresented_source_bins'] = 1
    value['compartment_bin_coverage']['unrepresented_source_bins'] = 2
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, config)
    value['compartment_bin_coverage']['unrepresented_source_bins'] = 1
    value['compartment_events']['events'][0][1] = 1.01
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, config)


def test_crossing_summary_must_agree_with_maximum_voltage_screen():
    value = preview()
    value["source_voltage_range_mv"] = {"minimum": -70., "maximum": -60.}
    value["source_all_compartments_voltage_range_mv"] = {"minimum": -70., "maximum": 30.}
    value["source_unobserved_threshold_candidates"] = 0
    value["source_compartment_crossings"] = {"sources_checked": 1, "outside_selected_only": 1,
                                              "earlier_than_selected": 0,
                                              "initial_above_sources": 0}
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())
    value["source_unobserved_threshold_candidates"] = 1
    validate_field_graph_preview(value, configuration())


def test_replay_compartment_range_is_validated():
    value = preview()
    value['replay_all_compartments_voltage_range_mv'] = {'minimum': -500., 'maximum': 40.}
    validate_field_graph_preview(value, configuration())
    value['replay_all_compartments_voltage_range_mv']['minimum'] = float('nan')
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())


def test_accepts_current_archive_only_with_inner_manifest_hash():
    value = manifest()
    value["files"].append({"name": "currents.zip", "bytes": 120, "sha256": "c" * 64})
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256="a" * 64)
    value["current_manifest_sha256"] = "d" * 64
    validate_field_graph_manifest(value, configuration_sha256="a" * 64)
    validate_field_graph_manifest(value, configuration_sha256="a" * 64, retain_currents=True)
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256="a" * 64, retain_currents=False)
    value["current_manifest_sha256"] = "invalid"
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256="a" * 64)
    value["current_manifest_sha256"] = "d" * 64
    value["files"].pop()
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256="a" * 64)
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(manifest(), configuration_sha256="a" * 64,
                                      retain_currents=True)


@pytest.mark.parametrize("change", ["duplicate", "path", "hash", "identity"])
def test_rejects_invalid_manifest(change):
    value = manifest()
    if change == "duplicate":
        value["files"][0] = copy.deepcopy(value["files"][1])
    elif change == "path":
        value["files"][0]["name"] = "../graph.bin"
    elif change == "hash":
        value["files"][0]["sha256"] = "wrong"
    else:
        value["configuration_sha256"] = "c" * 64
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_manifest(value, configuration_sha256="a" * 64)


@pytest.mark.parametrize("change", ["nan", "order", "saturation", "count", "missing", "spikes"])
def test_rejects_invalid_preview(change):
    value = preview()
    if change == "nan":
        value["neural_uv"][1] = float("nan")
    elif change == "order":
        value["time_ms"][1] = 0.0
    elif change == "saturation":
        value["acquisition"]["valid_samples"][1] = True
    elif change == "count":
        value["source_cells"] = 2
    elif change == "missing":
        value.pop("acquisition")
    else:
        value["network_spikes_by_ms"][1] = -1
    with pytest.raises(InvalidFieldGraphManifest):
        validate_field_graph_preview(value, configuration())
