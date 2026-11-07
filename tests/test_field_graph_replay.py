import numpy as np
import pytest

from service.application.field.field_graph_replay import run_field_graph_replay
from tests.test_forced_network import graph


def channel(neural, artifact):
    time = np.arange(101) * 0.1
    return {
        "time_ms": time,
        "stimulus_fraction": np.where((time >= 2) & (time <= 3), 1.0, 0.0),
        "stimulus_artifact_uv": np.asarray(artifact, dtype=float),
        "neural_uv": np.asarray(neural, dtype=float),
        "cells": 1,
        "ordered_sources_sha256": "a" * 64,
        "stimulation_parameters": {"current_na": 10},
        "electrode_um": [0.0, 1.0, 0.0],
        "reference_um": [0.0, 2.0, 0.0],
        "coordinate_frame": "native",
        "source_model": "pointsource",
    }


def setup(monkeypatch):
    artifact = np.zeros(101)
    artifact[20:31] = 10
    first = channel(np.ones(101), artifact)
    second = channel(np.full(101, 2.0), artifact)
    monkeypatch.setattr(
        "service.application.field.field_graph_replay.run_field_driven_network",
        lambda *_args, **_kwargs: {"recording": first, "network": {}},
    )
    monkeypatch.setattr(
        "service.application.field.field_graph_replay.encode_forced_spikes",
        lambda *_args: (b"binary", {"manifest_sha256": "test"}, "b" * 64),
    )
    monkeypatch.setattr(
        "service.application.field.field_graph_replay.replay_independent_population",
        lambda *_args, **_kwargs: second,
    )
    return first, second


def arguments():
    return dict(
        source_cells=[{"body_id": 10, "child_node_id": 2, "threshold_mv": -20}],
        replay_ids=[20],
        simulation_parameters={"duration_ms": 10},
        schedule_parameters={"duration_ms": 10},
        seed=1,
        recording={
            "electrode_um": [0, 1, 0],
            "reference_um": [0, 2, 0],
            "source_model": "pointsource",
        },
    )


def test_combined_signal_sums_cells_but_not_the_common_artifact(monkeypatch):
    first, second = setup(monkeypatch)
    result = run_field_graph_replay(
        None,
        graph(),
        [],
        **arguments(),
        acquisition={"low_hz": 100, "high_hz": 1000, "recovery_ms": 0.5, "clip_uv": 5},
    )
    output = result["recording"]
    np.testing.assert_array_equal(output["neural_uv"], first["neural_uv"] + second["neural_uv"])
    np.testing.assert_array_equal(output["stimulus_artifact_uv"], first["stimulus_artifact_uv"])
    np.testing.assert_array_equal(
        output["total_uv"], output["neural_uv"] + first["stimulus_artifact_uv"]
    )
    assert result["acquisition"]["saturated_samples"].any()
    assert output["source_cells"] == output["replay_cells"] == 1


def test_rejects_overlap_and_unknown_target_before_calculation():
    args = arguments()
    for ids in ([10], [40], [20, 20]):
        with pytest.raises(ValueError):
            run_field_graph_replay(None, graph(), [], **{**args, "replay_ids": ids})


def test_result_configuration_is_detached_from_mutable_request(monkeypatch):
    setup(monkeypatch)
    args = arguments()
    result = run_field_graph_replay(None, graph(), [], **args)
    args["source_cells"][0]["threshold_mv"] = 100
    assert result["configuration"]["source_cells"][0]["threshold_mv"] == -20


@pytest.mark.parametrize("field", ["stimulus_artifact_uv", "time_ms", "electrode_um"])
def test_rejects_mismatched_recording_before_combining(monkeypatch, field):
    _, second = setup(monkeypatch)
    second[field] = np.array([99]) if field != "electrode_um" else [99.0, 1.0, 0.0]
    with pytest.raises(ValueError, match="differ|same"):
        run_field_graph_replay(None, graph(), [], **arguments())
