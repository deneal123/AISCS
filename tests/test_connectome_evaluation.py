"""Contract-only fixtures below do not validate the scientific generator."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from service.application.connectome_evaluation import cases, evaluate_connectome
from service.domain.connectome_signals import features
from service.domain.recording_noise import add_noise


def test_features_use_only_the_finite_signal_and_reject_wrong_grid():
    time = np.linspace(0, 200, 8001)
    signal = np.sin(time) * 0.1
    np.testing.assert_array_equal(features(time, signal), features(time, -signal))
    with pytest.raises(ValueError, match="200 ms"):
        features(time[::2], signal[::2])
    signal[100] = np.nan
    with pytest.raises(ValueError, match="finite"):
        features(time, signal)


def test_shared_noise_preserves_existing_seeded_recording_exactly():
    clean = np.linspace(-1, 1, 100)
    old = clean + np.random.default_rng(np.random.SeedSequence([71, 917])).normal(
        0, 0.05, clean.shape
    )
    np.testing.assert_array_equal(add_noise(clean, 71, 0.05), old)


class ContractEngine:
    def __init__(self):
        self.calls = 0

    def simulate(self, config):
        self.calls += 1
        time = np.linspace(0, 200, 8001)
        # Deliberately simple fixture for state-machine checks only.
        level = {"none": 0, "weak": 1, "strong": 2}[config.stimulus]
        signal = np.sin(time) * level
        return SimpleNamespace(time_ms=time, fixture=signal, seconds=0.0)


class ContractRecorder:
    def record(self, config, dynamics):
        return dynamics.fixture


def protocol_path(tmp_path):
    source = Path(__file__).resolve().parents[1] / "validation/male-cns-v1/protocol.json"
    protocol = json.loads(source.read_text())
    protocol.update(
        regions=["thorax"],
        groups_per_region=6,
        split_groups_per_region={"train": 2, "validation": 2, "test": 2},
    )
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol))
    return path, protocol


def test_all_conditions_of_a_group_stay_together_with_unique_region_seeds(tmp_path):
    source = Path(__file__).resolve().parents[1] / "validation/male-cns-v1/protocol.json"
    rows = cases(json.loads(source.read_text()))
    groups = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    assert len(rows) == 480 and len(groups) == 160
    assert len({items[0]["configuration"]["seed"] for items in groups.values()}) == len(groups)
    for items in groups.values():
        assert len({row["partition"] for row in items}) == 1
        assert {row["label"] for row in items} == {"none", "weak", "strong"}


def test_freeze_resume_and_heldout_access_guards(tmp_path):
    protocol, _ = protocol_path(tmp_path)
    output = tmp_path / "evaluation"
    engine = ContractEngine()
    recorder, identity = ContractRecorder(), {"sha256": "unit-test-only"}
    args = (output, protocol)

    def progress(*args, **kwargs):
        pass

    with pytest.raises(ValueError, match="frozen"):
        evaluate_connectome(*args, "test", engine, recorder, identity, progress)
    report = evaluate_connectome(*args, "development", engine, recorder, identity, progress)
    assert report["test_accessed"] is False and engine.calls == 12
    candidate = (output / "candidate.json").read_bytes()
    evaluate_connectome(*args, "development", engine, recorder, identity, progress)
    assert engine.calls == 12
    final = evaluate_connectome(*args, "test", engine, recorder, identity, progress)
    assert engine.calls == 18 and final["test_groups"] == 2
    assert final["sizes"] == {"train": 6, "validation": 6, "test": 6}
    assert (output / "candidate.json").read_bytes() == candidate
    with pytest.raises(ValueError, match="runtime changed"):
        evaluate_connectome(*args, "test", engine, recorder, {"sha256": "changed"}, progress)
    (output / "frozen.json").unlink()
    with pytest.raises(ValueError, match="prevents re-fitting"):
        evaluate_connectome(*args, "development", engine, recorder, identity, progress)
