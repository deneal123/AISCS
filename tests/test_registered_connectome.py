"""Opt-in checks against the exact registered dataset, never substitute sample graphs."""

import json
import os
from pathlib import Path

import numpy as np
import pytest

from service.contracts import SimulationConfig
from service.infrastructure.connectome.dataset import load_registered_graph
from service.infrastructure.connectome.network import run_network
from service.main import build_generation

pytestmark = pytest.mark.skipif(
    not os.environ.get("GENERATOR_TEST_CONNECTOME"), reason="Requires registered MaleCNS dataset"
)


@pytest.fixture(scope="module")
def graph():
    return load_registered_graph(Path(os.environ["GENERATOR_TEST_CONNECTOME"]))


def test_registered_regions_and_source_identity(graph):
    assert graph.size == 166700 and len(graph.posts) == 25582938
    assert int(graph.counts.sum()) == 124177617
    expected = {
        "head": 1733,
        "thorax": 1877,
        "front_left": 151,
        "front_right": 115,
        "middle_left": 378,
        "middle_right": 428,
        "hind_left": 394,
        "hind_right": 411,
    }
    for region, count in expected.items():
        assert len(graph.stimulus_indices(region)) == count
    with pytest.raises(ValueError, match="No registered"):
        graph.stimulus_indices("abdomen")


def test_full_graph_quiet_propagation_and_exact_repeat(graph):
    first = None
    for seed, stimulus in [
        (1, "none"),
        (1, "strong"),
        (2, "strong"),
        (3, "strong"),
        (1, "strong"),
        (1, "weak"),
    ]:
        result = run_network(graph, seed=seed, stimulus=stimulus, region="thorax", duration_ms=100)
        assert len(result.counts) == graph.size
        assert result.counts.sum() == len(result.spike_neurons)
        assert np.isfinite(result.final_voltage_relative_mv).all()
        assert np.isfinite(result.final_synaptic_drive_mv).all()
        if stimulus == "none":
            assert len(result.spike_neurons) == 0
            continue
        assert result.metadata["spikes_outside_input_population"] > 0
        if seed == 1 and stimulus == "strong":
            if first is not None:
                for name, expected in first.items():
                    np.testing.assert_array_equal(getattr(result, name), expected)
            else:
                first = {
                    name: getattr(result, name).copy()
                    for name in (
                        "spike_neurons",
                        "spike_times_ms",
                        "counts",
                        "final_voltage_relative_mv",
                    )
                }


def test_full_export_and_passive_recording_have_separate_units_and_cache(
    tmp_path, monkeypatch, graph
):
    monkeypatch.setenv("GENERATOR_CONNECTOME_DIR", os.environ["GENERATOR_TEST_CONNECTOME"])
    monkeypatch.setenv("GENERATOR_WORK_DIR", str(tmp_path / "runtime"))
    generation = build_generation()
    base = SimulationConfig(
        model_id="male-cns-hybrid-v1",
        stimulus_region="thorax",
        duration_ms=100,
        stimulus="strong",
        seed=14201,
    )
    moved = base.model_copy(deep=True)
    moved.placement.electrode.y_um += 80
    first = generation.execute(base, tmp_path / "first")
    second = generation.execute(moved, tmp_path / "moved")
    assert second["dynamics_cache"]["status"] == "hit"
    assert first["dynamics_cache"]["data_sha256"] == second["dynamics_cache"]["data_sha256"]
    with np.load(tmp_path / "first/states.npz") as a, np.load(tmp_path / "moved/states.npz") as b:
        np.testing.assert_array_equal(a["membrane_current_na"], b["membrane_current_na"])
    a = json.loads((tmp_path / "first/preview.json").read_text())
    b = json.loads((tmp_path / "moved/preview.json").read_text())
    assert a["signal_uv"] != b["signal_uv"]
    assert a["prediction"] is None and b["prediction"] is None
    assert len(first["files"]) == 14
    assert sum(a["connectome"]["spikes_by_ms"]) == a["connectome"]["spikes"]
    assert a["connectome"]["scene"]["source_positioned_nodes"] == 140638
    assert a["connectome"]["scene"]["schematic_nodes"] == 26062
    from service.infrastructure.connectome.engine import RecordingEvaluationEngine

    equivalent = RecordingEvaluationEngine(graph).simulate(base)
    with np.load(tmp_path / "first/states.npz") as states:
        np.testing.assert_array_equal(equivalent.membrane_current_na, states["membrane_current_na"])
        np.testing.assert_array_equal(equivalent.time_ms, states["time_ms"])
    with pytest.raises(ValueError, match="complete registered network"):
        generation.writer.write(base, equivalent, tmp_path / "forbidden_partial_export")
