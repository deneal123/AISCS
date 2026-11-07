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


def test_transmembrane_current_balance_for_each_closed_cell():
    # The present model has synaptic membrane currents but no intracellular
    # current clamp. Axial currents cancel over all segments of each cell.
    dynamics = simulate(SimulationConfig(duration_ms=100, stimulus="strong", noise_uv=0))
    assert np.max(np.abs(dynamics.membrane_current_na)) > 0.01
    for cell in range(6):
        total = dynamics.membrane_current_na[dynamics.cell_ids == cell].sum(axis=0)
        assert np.max(np.abs(total)) < 1e-8


def test_local_signal_spatial_refinement_for_one_prescribed_scenario(monkeypatch):
    import service.infrastructure.neuron.solver as solver

    config = SimulationConfig(duration_ms=100, stimulus="strong", noise_uv=0, adaptation=0)
    original = solver.sections_for_cell
    signals = []
    for factor in (1, 3, 5):

        def refined(cell, factor=factor):
            return [
                (name, first, last, diameter, count * factor)
                for name, first, last, diameter, count in original(cell)
            ]

        monkeypatch.setattr(solver, "sections_for_cell", refined)
        dynamics = solver.simulate(config)
        signals.append(forward_recording(config, dynamics))
    # Refined soma indices are not exported by this local test; only compare
    # currents and the resulting voltage, never its spike journal.
    reference_rms = np.sqrt(np.mean(signals[-1] ** 2))
    assert reference_rms > 0

    def error(signal):
        return np.sqrt(np.mean((signal - signals[-1]) ** 2)) / reference_rms

    assert error(signals[0]) < 0.01
    assert error(signals[1]) < 0.002
