import numpy as np
import pytest

from service.application.feedback.gpu_replay import iter_gpu_replay_batches, replay_gpu_batch


@pytest.fixture
def simulation():
    return {
        "source_um": [0.0, 0.0, 0.0],
        "return_um": [10.0, 0.0, 0.0],
        "current_na": 1.0,
        "conductivity_s_m": 0.3,
        "clearance_um": 1.0,
        "duration_ms": 10.0,
        "dt_ms": 0.025,
        "pulse_start_ms": 2.0,
        "pulse_end_ms": 3.0,
        "rise_time_ms": 0.0,
        "interphase_gap_ms": 0.0,
        "pulse_shape": "monophasic",
        "pulse_count": None,
        "pulse_interval_ms": None,
        "nseg_per_edge": 1,
        "allow_disconnected": True,
    }


def test_bridge_passes_original_events_and_midpoint_waveform(monkeypatch, simulation):
    captured = {}

    def run(requests, directories, waveform, **kwargs):
        captured.update(requests=requests, waveform=waveform, kwargs=kwargs)
        return ["result"]

    monkeypatch.setattr("service.application.feedback.gpu_replay.run_registered_batch", run)
    requests = [{"id": 1, "expected_sha256": "a" * 64, "events": []}]
    assert replay_gpu_batch(requests, [], simulation, output_budget_bytes=10000) == ["result"]
    assert captured["requests"] is requests
    assert captured["waveform"].shape == (401,)
    np.testing.assert_array_equal(captured["waveform"][:4], 0.0)
    assert "allow_disconnected" not in captured["kwargs"]["recording_config"]


def test_bridge_accepts_optional_pulse_fields_omitted(monkeypatch, simulation):
    simulation.pop("pulse_count")
    simulation.pop("pulse_interval_ms")
    monkeypatch.setattr(
        "service.application.feedback.gpu_replay.run_registered_batch",
        lambda *args, **kwargs: ["result"],
    )
    assert replay_gpu_batch([], [], simulation, output_budget_bytes=10000) == ["result"]


def test_bridge_passes_005_ms_grid(monkeypatch, simulation):
    simulation["dt_ms"] = 0.05
    captured = {}

    def run(_requests, _directories, waveform, **kwargs):
        captured.update(waveform=waveform, **kwargs)
        return []

    monkeypatch.setattr("service.application.feedback.gpu_replay.run_registered_batch", run)
    replay_gpu_batch([], [], simulation, output_budget_bytes=10000)
    assert captured["dt_ms"] == 0.05
    assert captured["waveform"].shape == (201,)


@pytest.mark.parametrize(
    ("key", "value"), [("dt_ms", 0.1), ("nseg_per_edge", True), ("pulse_count", 0)]
)
def test_bridge_rejects_unsupported_configuration(simulation, key, value):
    simulation[key] = value
    with pytest.raises(ValueError):
        replay_gpu_batch([], [], simulation, output_budget_bytes=10000)


def test_streaming_replay_is_lazy_ordered_and_reports_completed_groups(monkeypatch, simulation):
    calls, progress = [], []

    def replay(group, *_args, **_kwargs):
        calls.append([row['id'] for row in group])
        return [{'id': row['id']} for row in group]

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', replay)
    stream = iter_gpu_replay_batches([{'id': i} for i in range(1, 6)], [], simulation,
        max_cells=2, output_budget_bytes=10000, progress=lambda a, b: progress.append((a, b)))
    assert next(stream)['id'] == 1
    assert calls == [[1, 2]] and progress == []
    assert [row['id'] for row in stream] == [2, 3, 4, 5]
    assert calls == [[1, 2], [3, 4], [5]]
    assert progress == [(2, 5), (4, 5), (5, 5)]


def test_streaming_replay_rejects_duplicate_and_reordered_ids(monkeypatch, simulation):
    with pytest.raises(ValueError, match='request'):
        list(iter_gpu_replay_batches([{'id': 1}, {'id': 1}], [], simulation,
                                    max_cells=2, output_budget_bytes=10000))
    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch',
                        lambda *_a, **_k: [{'id': 2}, {'id': 1}])
    with pytest.raises(ValueError, match='reordered'):
        list(iter_gpu_replay_batches([{'id': 1}, {'id': 2}], [], simulation,
                                    max_cells=2, output_budget_bytes=10000))


def test_streaming_replay_stops_before_next_group_on_cancellation(monkeypatch, simulation):
    calls = []

    def replay(group, *_args, **_kwargs):
        calls.append([row['id'] for row in group])
        return [{'id': row['id']} for row in group]

    def cancelled():
        if calls:
            raise RuntimeError('cancelled')

    monkeypatch.setattr('service.application.feedback.gpu_replay.replay_gpu_batch', replay)
    stream = iter_gpu_replay_batches([{'id': 1}, {'id': 2}], [], simulation,
        max_cells=1, output_budget_bytes=10000, check_cancelled=cancelled)
    assert next(stream)['id'] == 1
    with pytest.raises(RuntimeError, match='cancelled'):
        next(stream)
    assert calls == [[1]]
