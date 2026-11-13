import numpy as np

from service.infrastructure.stimulation.population.preview import (
    fragment_population_preview,
)


def test_preview_preserves_stimulus_boundaries_and_graph_spikes():
    time = np.linspace(0, 10, 10001)
    stimulus = np.zeros_like(time)
    stimulus[1234:1244] = np.linspace(0, 1, 10)
    stimulus[1244:1254] = 1
    stimulus[1254:1264] = np.linspace(1, 0, 10)
    arrays = {
        "time_ms": time,
        "neural_uv": np.zeros_like(time),
        "total_uv": np.zeros_like(time),
        "stimulus_fraction": stimulus,
        "spike_times_ms": np.array([2, 2, 4]),
    }
    result = fragment_population_preview(
        arrays, source_count=2, duration_ms=10, edge_event_count=3
    )
    assert result["stimulus_boundaries_preserved"] is True
    reconstructed = np.interp(time, result["time_ms"], result["stimulus_fraction"])
    np.testing.assert_allclose(reconstructed, stimulus, atol=1e-12)
    assert len(result["time_ms"]) <= 4096
    assert result["network_spikes_by_ms"][2] == 2
    assert result["network_spikes_by_ms"][4] == 1


def test_high_frequency_preview_declares_lost_boundaries():
    time = np.linspace(0, 10, 10001)
    stimulus = np.resize(np.array([0.0, 1.0]), len(time))
    arrays = {
        "time_ms": time,
        "neural_uv": np.zeros_like(time),
        "total_uv": np.zeros_like(time),
        "stimulus_fraction": stimulus,
        "spike_times_ms": np.array([], dtype=int),
    }
    result = fragment_population_preview(
        arrays, source_count=1, duration_ms=10, edge_event_count=0
    )
    assert result["stimulus_boundaries_preserved"] is False
    assert len(result["time_ms"]) <= 4096
