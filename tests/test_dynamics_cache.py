import json

import numpy as np

from service.contracts import SimulationConfig
from service.infrastructure.execution.dynamics_cache import CachedDynamics
from service.infrastructure.lfpy.recording import forward_recording
from service.infrastructure.neuron.solver import NeuronEngine


class CountingEngine(NeuronEngine):
    def __init__(self):
        self.calls = 0

    def simulate(self, config):
        self.calls += 1
        return super().simulate(config)


def test_move_electrode_reuses_exact_currents_and_recomputes_signal(tmp_path):
    engine = CountingEngine()
    cache = CachedDynamics(engine, tmp_path, engine.identity(), 32 * 1024 * 1024)
    config = SimulationConfig(duration_ms=100, stimulus="strong", seed=827)
    original = cache.simulate(config)
    moved = config.model_copy(deep=True)
    moved.placement.electrode.y_um += 80
    reused = cache.simulate(moved)
    assert engine.calls == 1
    assert original.cache_info["status"] == "miss"
    assert reused.cache_info["status"] == "hit"
    assert original.cache_info["data_sha256"] == reused.cache_info["data_sha256"]
    np.testing.assert_array_equal(original.membrane_current_na, reused.membrane_current_na)
    assert original.input_events == reused.input_events
    assert not np.allclose(forward_recording(config, original), forward_recording(moved, reused))
    noisy = moved.model_copy(update={"noise_uv": 1.0, "conductivity_s_m": 0.6})
    assert cache.simulate(noisy).cache_info["status"] == "hit"
    assert engine.calls == 1
    changed = config.model_copy(update={"seed": 828})
    assert cache.simulate(changed).cache_info["status"] == "miss"
    assert engine.calls == 2
    changed_engine = CachedDynamics(
        engine, tmp_path, {**engine.identity(), "revision": "new"}, 32 * 1024 * 1024
    )
    assert changed_engine.simulate(config).cache_info["status"] == "miss"
    assert engine.calls == 3


def test_corrupt_cache_recomputes_instead_of_using_unverified_arrays(tmp_path):
    engine = CountingEngine()
    cache = CachedDynamics(engine, tmp_path, engine.identity(), 32 * 1024 * 1024)
    config = SimulationConfig(duration_ms=100, seed=829)
    original = cache.simulate(config)
    (tmp_path / (cache.key(config) + ".npz")).write_bytes(b"damaged cache")
    recomputed = cache.simulate(config)
    assert engine.calls == 2
    assert recomputed.cache_info["status"] == "miss_invalid_or_unavailable"
    np.testing.assert_array_equal(original.membrane_current_na, recomputed.membrane_current_na)


def test_zero_budget_disables_cache_without_affecting_generation(tmp_path):
    engine = CountingEngine()
    cache = CachedDynamics(engine, tmp_path, engine.identity(), 0)
    result = cache.simulate(SimulationConfig(duration_ms=100))
    assert result.cache_info["status"] == "disabled"
    assert not list(tmp_path.iterdir())


def test_cache_rejects_changed_event_journal_metadata(tmp_path):
    engine = CountingEngine()
    cache = CachedDynamics(engine, tmp_path, engine.identity(), 32 * 1024 * 1024)
    config = SimulationConfig(duration_ms=100, stimulus="strong", seed=830)
    original = cache.simulate(config)
    path = tmp_path / (cache.key(config) + ".json")
    metadata = json.loads(path.read_text())
    metadata["input_events"][0]["time_ms"] += 1
    path.write_text(json.dumps(metadata))
    recovered = cache.simulate(config)
    assert recovered.cache_info["status"] == "miss_invalid_or_unavailable"
    assert recovered.input_events == original.input_events
    assert engine.calls == 2
