"""Run after installing the built wheel into /tmp/isolated, without source cwd."""

from pathlib import Path

import numpy as np

import service
from service.contracts import SimulationConfig
from service.infrastructure.recognition.connectome_classifier import predict_connectome
from service.settings import connectome_model_path, model_path

assert Path(service.__file__).is_relative_to(Path("/tmp/isolated"))
assert model_path().is_file() and connectome_model_path().is_file()
config = SimulationConfig(model_id="male-cns-hybrid-v1", stimulus_region="thorax")
prediction, state = predict_connectome(np.linspace(0, 200, 8001), np.zeros(8001), config)
assert state["state"] == "available" and prediction["model_id"] == "male-cns-recognition-v1"
print("Independent wheel loads both frozen models and verifies numerical source binding")
