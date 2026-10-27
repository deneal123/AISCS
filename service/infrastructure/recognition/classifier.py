import hashlib
import json

import numpy as np

from service.domain.signals import features
from service.settings import model_path


def predict(time_ms, signal_uv) -> dict | None:
    path = model_path()
    if not path.is_file():
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    x = (features(time_ms, signal_uv) - np.array(model["mean"])) / np.array(model["scale"])
    scores = np.array(model["coefficients"]) @ x + np.array(model["intercepts"])
    return {
        "class": model["classes"][int(np.argmax(scores))],
        "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "evaluation": model.get("evaluation"),
        "scope": "synthetic local-model stimulus; not pain classification",
    }
