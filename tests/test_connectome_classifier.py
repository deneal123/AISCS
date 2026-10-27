import json
from pathlib import Path

import numpy as np

from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.infrastructure.recognition.connectome_classifier import predict_connectome
from service.settings import connectome_model_path


def inputs():
    config = SimulationConfig.model_validate(catalog()["models"][1]["defaults"])
    time = np.linspace(0, 200, 8001)
    signal = np.sin(time) * 0.05
    return config, time, signal


def test_prediction_uses_signal_and_known_region_without_stimulus_label():
    config, time, signal = inputs()
    a, status = predict_connectome(time, signal, config.model_copy(update={"stimulus": "none"}))
    b, _ = predict_connectome(time, signal, config.model_copy(update={"stimulus": "strong"}))
    assert status["state"] == "available"
    assert a == b
    assert a["evaluation"]["test_groups"] == 4 and a["evaluation"]["test_realizations"] == 12
    assert a["overall_evaluation"]["test_groups"] == 32


def test_outside_checked_domain_never_silently_returns_local_prediction():
    config, time, signal = inputs()
    for update in (
        {"duration_ms": 100.0},
        {"excitability": 0.7},
        {"noise_uv": 1.0},
        {"conductivity_s_m": 0.6},
    ):
        prediction, status = predict_connectome(time, signal, config.model_copy(update=update))
        assert prediction is None and status["state"] == "outside_checked_domain"
    moved = config.model_copy(deep=True)
    moved.placement.reference.y_um += 10
    prediction, status = predict_connectome(time, signal, moved)
    assert prediction is None and status["state"] == "outside_checked_domain"


def test_changed_numerical_signature_and_bad_coefficients_are_rejected(tmp_path, monkeypatch):
    config, time, signal = inputs()
    baseline = json.loads(connectome_model_path().read_text())
    path = tmp_path / "model.json"
    monkeypatch.setenv("GENERATOR_CNS_MODEL_PATH", str(path))
    baseline["binding"]["numerical_identity"]["sha256"] = "changed"
    path.write_text(json.dumps(baseline))
    prediction, status = predict_connectome(time, signal, config)
    assert prediction is None and status["state"] == "incompatible"
    baseline = json.loads(
        (Path(__file__).resolve().parents[1] / "validation/male-cns-v1/classifier.json").read_text()
    )
    baseline["models"]["thorax"]["scale"][0] = 0
    path.write_text(json.dumps(baseline))
    prediction, status = predict_connectome(time, signal, config)
    assert prediction is None and status["state"] == "invalid_model"
