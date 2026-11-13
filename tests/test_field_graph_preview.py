from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.stimulation.acquisition import acquire_channel
from service.infrastructure.stimulation.field.graph_export import export_field_graph_replay
from service.infrastructure.stimulation.field.graph_preview import field_graph_preview
from tests.test_field_graph_export import example


def test_preview_flags_possible_missed_threshold_without_claiming_spike(monkeypatch):
    time = np.arange(4, dtype=float)
    arrays = {"time_ms": time, "neural_uv": time * 0, "total_uv": time * 0,
              "stimulus_fraction": time * 0,
              "source_0_voltage_mv": np.full(4, -65.),
              "source_0_event_ticks_ms": np.array([], dtype=int),
              "source_1_voltage_mv": np.array([-65., -10., -65., -65.]),
              "source_1_event_ticks_ms": np.array([1], dtype=int)}
    metadata = {"graph_description": {"duration_ms": 3}, "graph_sha256": "sha",
                "acquisition_settings": None, "configuration": {"replay_ids": [3]},
                "source_cells": [
                    {"selection": {"threshold_mv": -20.},
                     "all_voltage_range_mv": {"minimum": -65., "maximum": 10.},
                     "crossing_diagnostics": {"compartments_with_upward_crossing": 1,
                         "selected_crossings": 0, "selected_first_crossing_sample_ms": None,
                         "earliest_crossing_sample_ms": 1., "initial_at_or_above_threshold": 0}},
                    {"selection": {"threshold_mv": -20.},
                     "all_voltage_range_mv": {"minimum": -65., "maximum": 15.},
                     "crossing_diagnostics": {"compartments_with_upward_crossing": 1,
                         "selected_crossings": 1, "selected_first_crossing_sample_ms": 1.,
                         "earliest_crossing_sample_ms": 1., "initial_at_or_above_threshold": 0}},
                ]}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: {"arrays": arrays, "metadata": metadata, "graph_binary": b""})
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2, 3]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph)
    assert preview["source_unobserved_threshold_candidates"] == 1
    assert preview["source_compartment_crossings"] == {
        "sources_checked": 2, "outside_selected_only": 1, "earlier_than_selected": 0,
        "initial_above_sources": 0,
    }
    del metadata["source_cells"][0]["all_voltage_range_mv"]
    assert "source_unobserved_threshold_candidates" not in field_graph_preview(None, graph)


def test_preview_retains_stimulus_even_without_recording_response(monkeypatch):
    time = np.arange(10, dtype=float)
    stimulus = np.zeros(10)
    stimulus[3], stimulus[6] = 1, -1
    metadata = {"graph_description": {"duration_ms": 9}, "graph_sha256": "sha",
                "acquisition_settings": None, "source_cells": [1],
                "configuration": {"replay_ids": [2]}}
    verified = {"arrays": {"time_ms": time, "neural_uv": np.zeros(10),
                           "total_uv": np.zeros(10), "stimulus_fraction": stimulus,
                           "source_0_voltage_mv": np.array([-65., -65., -65., -17000., -65.,
                                                            -65., -65., -65., -65., -65.])},
                "metadata": metadata, "graph_binary": b""}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: verified)
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph, bins=1)
    assert 1 in preview["stimulus_fraction"] and -1 in preview["stimulus_fraction"]
    assert preview["source_voltage_range_mv"] == {"minimum": -17000., "maximum": -65.}
    assert all(t in preview["time_ms"] for t in (2, 3, 4, 5, 6, 7))


def test_preview_with_all_extrema_respects_backend_sample_limit(monkeypatch):
    size = 4090
    arrays = {"time_ms": np.linspace(0, 1000, size), "valid_samples": np.ones(size, bool),
              "saturated_samples": np.zeros(size, bool)}
    names = ("neural_uv", "total_uv", "stimulus_fraction", "filtered_total_uv")
    for offset, name in enumerate(names):
        signal = np.zeros(size)
        signal[1 + offset * 2::10] = -1
        signal[2 + offset * 2::10] = 1
        arrays[name] = signal
    metadata = {"graph_description": {"duration_ms": 1000}, "graph_sha256": "sha",
                "acquisition_settings": {}, "source_cells": [1],
                "configuration": {"replay_ids": [2]}}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: {"arrays": arrays, "metadata": metadata, "graph_binary": b""})
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph)
    assert 0 < preview["shown_samples"] <= size
    assert preview["shown_samples"] <= 4096


def test_short_pulse_keeps_inactive_samples_on_both_sides(monkeypatch):
    time = np.arange(101, dtype=float)
    stimulus = np.zeros(len(time))
    stimulus[45:48] = 1
    metadata = {"graph_description": {"duration_ms": 100}, "graph_sha256": "sha",
                "acquisition_settings": None, "source_cells": [1],
                "configuration": {"replay_ids": [2]}}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: {"arrays": {"time_ms": time, "neural_uv": np.zeros(len(time)),
                                               "total_uv": np.zeros(len(time)),
                                               "stimulus_fraction": stimulus},
                                    "metadata": metadata, "graph_binary": b""})
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph, bins=1)
    assert all(t in preview["time_ms"] for t in (44, 45, 47, 48))
    assert np.interp(30, preview["time_ms"], preview["stimulus_fraction"]) == 0
    assert np.interp(70, preview["time_ms"], preview["stimulus_fraction"]) == 0


def test_preview_preserves_ramp_and_plateau_not_just_peak(monkeypatch):
    time = np.arange(101, dtype=float)
    stimulus = np.interp(time, [0, 20, 30, 60, 70, 100], [0, 0, 1, 1, 0, 0])
    metadata = {"graph_description": {"duration_ms": 100}, "graph_sha256": "sha",
                "acquisition_settings": None, "source_cells": [1],
                "configuration": {"replay_ids": [2]}}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: {"arrays": {"time_ms": time, "neural_uv": np.zeros(len(time)),
                                               "total_uv": np.zeros(len(time)),
                                               "stimulus_fraction": stimulus},
                                    "metadata": metadata, "graph_binary": b""})
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph, bins=1)
    np.testing.assert_allclose(np.interp(time, preview["time_ms"], preview["stimulus_fraction"]),
                               stimulus, atol=1e-12)


def test_high_frequency_stimulus_keeps_preview_bounded(monkeypatch):
    size = 10000
    arrays = {"time_ms": np.arange(size, dtype=float), "neural_uv": np.zeros(size),
              "total_uv": np.zeros(size), "stimulus_fraction": np.arange(size) % 2}
    metadata = {"graph_description": {"duration_ms": size - 1}, "graph_sha256": "sha",
                "acquisition_settings": None, "source_cells": [1],
                "configuration": {"replay_ids": [2]}}
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview.load_verified_field_graph_replay",
                        lambda *_: {"arrays": arrays, "metadata": metadata, "graph_binary": b""})
    monkeypatch.setattr("service.infrastructure.stimulation.field.graph_preview._read_verified_spike_arrays",
                        lambda *_: (np.array([], dtype=int), np.array([], dtype=float)))
    graph = SimpleNamespace(ids=np.array([1, 2]), provenance={"manifest_sha256": "sha"})
    preview = field_graph_preview(None, graph)
    assert preview["shown_samples"] <= 4096
    assert preview["selection"] == "per-bin endpoints and signal extrema"


def test_preview_retains_extrema_and_conservatively_aggregates_validity(tmp_path):
    model, result, evidence, provenance = example()
    result['source']['sources'][0]['all_voltage_range_mv'] = {'minimum': -500., 'maximum': 50.}
    result['replay']['all_voltage_range_mv'] = {'minimum': -600., 'maximum': 40.}
    result["recording"]["neural_uv"] = np.array([1.0, 1.0, 4.0, 1.0, 1.0, 1.0, 1.0])
    result["recording"]["stimulus_artifact_uv"] = np.array([0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    result["recording"]["stimulus_fraction"] = np.array([0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    result["recording"]["total_uv"] = (
        result["recording"]["neural_uv"] + result["recording"]["stimulus_artifact_uv"]
    )
    result["source"]["recording"]["neural_uv"] = result["recording"]["neural_uv"] - 0.6
    config = {"low_hz": 10, "high_hz": 200, "recovery_ms": 0, "clip_uv": 5}
    result["configuration"]["acquisition"] = config
    data = result["recording"]
    result["acquisition"] = acquire_channel(
        data["time_ms"],
        data["neural_uv"],
        data["stimulus_artifact_uv"],
        data["stimulus_fraction"],
        **config,
    )
    target = tmp_path / "result"
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    preview = field_graph_preview(target, model, bins=2)
    assert preview['source_all_compartments_voltage_range_mv'] == {'minimum': -500., 'maximum': 50.}
    assert preview['replay_all_compartments_voltage_range_mv'] == {'minimum': -600., 'maximum': 40.}
    assert 4.0 in preview["neural_uv"]
    filtered = result["acquisition"]["filtered_total_uv"]
    assert filtered[:3].max() in preview["acquisition"]["filtered_total_uv"]
    assert filtered[3:].min() in preview["acquisition"]["filtered_total_uv"]
    for time, valid, saturated in zip(
        preview["time_ms"],
        preview["acquisition"]["valid_samples"],
        preview["acquisition"]["saturated_samples"],
        strict=True,
    ):
        if time < 3:
            assert not valid and saturated
        else:
            assert not valid and not saturated
    assert preview["source_cells"] == preview["replay_cells"] == 1
    assert preview["network_spikes_by_ms"] == [0, 1, 0, 1, 0, 1, 0]
    assert preview["acquisition"]["mask_intervals"][-1]["end_ms"] == 6


def test_final_saturated_sample_has_visible_time_interval(tmp_path):
    model, result, evidence, provenance = example()
    data = result["recording"]
    data["stimulus_artifact_uv"] = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0])
    data["stimulus_fraction"] = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0])
    data["total_uv"] = data["neural_uv"] + data["stimulus_artifact_uv"]
    config = {"low_hz": 10, "high_hz": 200, "recovery_ms": 0, "clip_uv": 5}
    result["configuration"]["acquisition"] = config
    result["acquisition"] = acquire_channel(
        data["time_ms"],
        data["neural_uv"],
        data["stimulus_artifact_uv"],
        data["stimulus_fraction"],
        **config,
    )
    target = tmp_path / "result"
    export_field_graph_replay(result, model, target, evidence=evidence, provenance=provenance)
    last = field_graph_preview(target, model, bins=7)["acquisition"]["mask_intervals"][-1]
    assert last == {"start_ms": 5.5, "end_ms": 6.0, "valid": False, "saturated": True}


@pytest.mark.parametrize("bins", [0, True, 1.5])
def test_preview_rejects_invalid_bin_count(tmp_path, bins):
    with pytest.raises(ValueError, match="bins"):
        field_graph_preview(tmp_path, graph=None, bins=bins)
