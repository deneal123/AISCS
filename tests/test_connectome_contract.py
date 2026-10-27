import pytest

from service.contracts import SimulationConfig
from service.infrastructure.neuron.solver import simulate


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
