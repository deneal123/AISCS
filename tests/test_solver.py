import numpy as np

from service.contracts import SimulationConfig
from service.domain.geometry import local_geometry
from service.infrastructure.lfpy.recording import forward_recording
from service.infrastructure.neuron.solver import simulate


def test_repeat_same_seed_and_electrode_does_not_change_dynamics():
    cfg = SimulationConfig(duration_ms=100, stimulus="strong", adaptation=0)
    first, second = simulate(cfg), simulate(cfg)
    np.testing.assert_array_equal(first.voltage_mv, second.voltage_mv)
    np.testing.assert_array_equal(first.membrane_current_na, second.membrane_current_na)
    assert len(first.spikes) > 0
    assert first.input_events == second.input_events
    assert {event["cell_id"] for event in first.input_events} == {0, 1}
    assert all(event["weight_us"] == 0.009 for event in first.input_events)
    expected = local_geometry()
    np.testing.assert_array_equal(first.starts_um, expected["starts_um"])
    np.testing.assert_array_equal(first.ends_um, expected["ends_um"])
    assert first.soma_segment_ids == expected["soma_segment_ids"]
    shifted = cfg.model_copy(deep=True)
    shifted.placement.electrode.y_um += 80
    assert cfg.dynamics_digest() == shifted.dynamics_digest()
    assert not np.allclose(forward_recording(cfg, first), forward_recording(shifted, first))


def test_zero_drive_and_timestep_convergence():
    cfg = SimulationConfig(duration_ms=100, stimulus="none", noise_uv=0)
    zero = simulate(cfg)
    assert zero.spikes == []
    assert zero.input_events and all(event["weight_us"] == 0 for event in zero.input_events)
    cfg = SimulationConfig(duration_ms=100, stimulus="strong", noise_uv=0)
    first = simulate(cfg)
    finer = simulate(cfg.model_copy(update={"dt_ms": 0.0125}))
    # Check waveform convergence after interpolating both recordings to a common grid.
    a = forward_recording(cfg, first)
    b = np.interp(first.time_ms, finer.time_ms, forward_recording(cfg, finer))
    assert np.sqrt(np.mean((a - b) ** 2)) < max(0.5, np.sqrt(np.mean(a**2)) * 0.35)
