import numpy as np
import pytest

from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.infrastructure.neuron.solver import simulate


def test_default_input_is_localized_and_legacy_thorax_is_not_named_dorsal_skin():
    models = catalog(connectome_available=True)["models"]
    full = next(model for model in models if model["id"] == "male-cns-hybrid-v1")
    assert SimulationConfig(**full["defaults"]).stimulus_region == "front_left"
    pooled = next(region for region in full["input_regions"] if region["id"] == "thorax")
    assert "шести ног" in pooled["name"]
    exterior = full["exterior_contact_defaults"]
    config = SimulationConfig(**full["defaults"])
    for key, source in exterior["contacts"].items():
        point = np.asarray(getattr(config.placement, key).xyz())
        surface = (np.asarray(source["surface_mm"]) - exterior["origin_mm"]) * 1000
        normal = np.asarray(source["normal"])
        np.testing.assert_allclose(np.linalg.norm(normal), 1, atol=1e-12)
        np.testing.assert_allclose(point - surface, normal * 25, atol=0.0006)
        assert sum(source["barycentric"]) == pytest.approx(1)


def test_full_preset_cannot_silently_use_local_or_unregistered_input():
    with pytest.raises(ValueError, match="region"):
        SimulationConfig(model_id="male-cns-hybrid-v1")
    with pytest.raises(ValueError, match="Whole-body"):
        SimulationConfig(stimulus_region="head")
    with pytest.raises(ValueError, match="abdominal"):
        SimulationConfig(model_id="male-cns-hybrid-v1", stimulus_region="abdomen")
    with pytest.raises(ValueError, match="integer"):
        SimulationConfig(model_id="male-cns-hybrid-v1", stimulus_region="head", duration_ms=100.5)
    config = SimulationConfig(model_id="male-cns-hybrid-v1", stimulus_region="head")
    assert (
        config.dynamics_digest()
        != config.model_copy(update={"stimulus_region": "thorax"}).dynamics_digest()
    )


def test_projected_input_replaces_label_driven_local_stimulus():
    # An empty projection must remain quiet even with the label 'strong'.
    config = SimulationConfig(stimulus="strong", duration_ms=100)
    quiet = simulate(config, projected_events=[])
    assert quiet.spikes == [] and quiet.input_events == []
    driven = simulate(config, projected_events=[{"cell_id": 3, "time_ms": 30.0, "weight_us": 0.02}])
    assert any(event["cell_id"] == 3 for event in driven.spikes)
    assert driven.input_events == [{"cell_id": 3, "time_ms": 30.0, "weight_us": 0.02}]
