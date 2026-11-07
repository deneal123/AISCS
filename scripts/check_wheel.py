"""Run after installing the built wheel into /tmp/isolated, without source cwd."""

from pathlib import Path

import numpy as np

import service
from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.domain.surface_anchors import thorax_mesh
from service.infrastructure.recognition.connectome_classifier import predict_connectome
from service.settings import connectome_model_path, model_path

assert Path(service.__file__).is_relative_to(Path("/tmp/isolated"))
assert model_path().is_file() and connectome_model_path().is_file()
assert thorax_mesh()[1].shape == (18312, 3)
config = SimulationConfig(model_id="male-cns-hybrid-v1", stimulus_region="thorax")
prediction, state = predict_connectome(np.linspace(0, 200, 8001), np.zeros(8001), config)
assert state["state"] == "available" and prediction["model_id"] == "male-cns-recognition-v1"
full = catalog(connectome_available=True)["models"][1]
assert full["defaults"]["stimulus_region"] == "front_left"
assert full["exterior_contact_defaults"]["contacts"]
external = SimulationConfig(**full["defaults"])
prediction, state = predict_connectome(np.linspace(0, 200, 8001), np.zeros(8001), external)
assert prediction is None and state["state"] == "outside_checked_domain"
print("Independent wheel loads frozen models, exterior defaults and checked-domain boundary")
