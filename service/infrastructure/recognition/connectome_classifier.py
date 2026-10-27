"""Frozen, region-conditioned classifier; no stimulus label or state features."""

import hashlib
import json
import math

import numpy as np

from service.contracts import SimulationConfig
from service.domain.connectome_signals import FEATURES, VERSION, features
from service.infrastructure.recognition.connectome_identity import numerical_identity
from service.settings import connectome_model_path


def checked_domain_issue(config: SimulationConfig, protocol: dict) -> str:
    if config.model_id != protocol["preset"] or config.stimulus_region not in protocol["regions"]:
        return "Для этой модели или области распознавание не проверялось."
    fixed = protocol["fixed"]
    for field in ("duration_ms", "dt_ms", "conductivity_s_m"):
        if not math.isclose(getattr(config, field), fixed[field], rel_tol=0, abs_tol=1e-9):
            return "Длительность, шаг или проводимость отличаются от проверенного протокола."
    if any(
        not math.isclose(value, expected, rel_tol=0, abs_tol=1e-9)
        for value, expected in zip(
            config.placement.reference.xyz(), fixed["reference_um"], strict=True
        )
    ):
        return "Положение REF выходит за проверенные условия распознавания."
    for field, (low, high) in protocol["ranges"].items():
        value = (
            getattr(config.placement.electrode, field.removeprefix("electrode_"))
            if field.startswith("electrode_")
            else getattr(config, field)
        )
        if not low <= value <= high:
            return "Параметры модели, шум или положение E1 выходят за проверенные диапазоны."
    return ""


def predict_connectome(time_ms, signal_uv, config: SimulationConfig) -> tuple[dict | None, dict]:
    path = connectome_model_path()
    if not path.is_file():
        return None, {
            "state": "not_available",
            "reason": "Классификатор полной сети не установлен.",
        }
    try:
        raw = path.read_bytes()
        model = json.loads(raw)
        if (
            model["feature_version"] != VERSION
            or model["binding"]["numerical_identity"] != numerical_identity()
        ):
            return None, {
                "state": "incompatible",
                "reason": (
                    "Численное ядро или обработка сигнала отличаются "
                    "от проверенной версии распознавания."
                ),
            }
        issue = checked_domain_issue(config, model["protocol"])
        if issue:
            return None, {"state": "outside_checked_domain", "reason": issue}
        weights = model["models"][config.stimulus_region]
        if weights["feature_names"] != FEATURES or weights["classes"] != ["none", "strong", "weak"]:
            raise ValueError("Classifier contract mismatch")
        mean, scale = np.asarray(weights["mean"]), np.asarray(weights["scale"])
        coefficients, intercepts = (
            np.asarray(weights["coefficients"]),
            np.asarray(weights["intercepts"]),
        )
        if (
            mean.shape != (len(FEATURES),)
            or scale.shape != mean.shape
            or coefficients.shape != (3, len(FEATURES))
            or intercepts.shape != (3,)
            or (scale <= 0).any()
            or not all(
                np.isfinite(value).all() for value in (mean, scale, coefficients, intercepts)
            )
        ):
            raise ValueError("Invalid classifier coefficients")
        scores = coefficients @ ((features(time_ms, signal_uv) - mean) / scale) + intercepts
        region = model["evaluation"]["regions"][config.stimulus_region]
        return {
            "class": weights["classes"][int(np.argmax(scores))],
            "model_sha256": hashlib.sha256(raw).hexdigest(),
            "model_id": model["id"],
            "region": config.stimulus_region,
            "evaluation": {
                **region,
                "sizes": {
                    name: 3 * count
                    for name, count in model["protocol"]["split_groups_per_region"].items()
                },
                "groups": model["protocol"]["split_groups_per_region"],
                "scope": model["evaluation"]["scope"],
                "limitations": model["evaluation"]["limitations"],
            },
            "overall_evaluation": {
                key: model["evaluation"][key]
                for key in (
                    "test_balanced_accuracy",
                    "test_realizations",
                    "test_groups",
                    "group_bootstrap_95_interval",
                )
            },
            "scope": "synthetic model-input conditions for a known region; not pain classification",
        }, {"state": "available"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, {
            "state": "invalid_model",
            "reason": "Проверка модели распознавания не пройдена; запись остаётся доступной.",
        }
