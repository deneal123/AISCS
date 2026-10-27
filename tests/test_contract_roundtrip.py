import json

import pytest

from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.domain.scene_context import registered_scene_contexts


def test_defaults_have_identical_digest_after_transport_and_revalidation():
    initial = SimulationConfig(seed=1, stimulus="strong")
    transferred = SimulationConfig.model_validate(json.loads(initial.model_dump_json()))
    assert transferred.model_dump() == initial.model_dump()
    assert transferred.digest() == initial.digest()
    assert transferred.dynamics_digest() == initial.dynamics_digest()


def test_optional_scene_context_preserves_legacy_digest_and_registered_round_trip():
    assert (
        SimulationConfig().digest()
        == "f1fcb7019c230c0c860fde999d503c06ccc94668e6844145bbaaa62ab5898e5c"
    )
    payload = catalog()["models"][0]["defaults"]
    config = SimulationConfig.model_validate(payload)
    assert (
        SimulationConfig.model_validate_json(config.model_dump_json()).digest() == config.digest()
    )
    payload["placement"]["registration"]["origin_mm"][0] += 1
    with pytest.raises(ValueError, match="Unregistered"):
        SimulationConfig.model_validate(payload)


def test_unregistered_mesh_and_outside_triangle_are_rejected():
    payload = catalog()["models"][0]["defaults"]
    payload["placement"]["registration"]["surface_anchor"] = {
        "mesh_part": "c_thorax",
        "triangle": 2001,
        "barycentric": [0.2, 0.3, 0.5],
    }
    with pytest.raises(ValueError, match="surface anchor"):
        SimulationConfig.model_validate(payload)


def test_new_flybody_and_legacy_flygym_contexts_remain_independently_replayable():
    contexts = registered_scene_contexts()
    assert contexts[0]["mesh_asset_id"].startswith("flybody-")
    assert contexts[1]["mesh_asset_id"].startswith("flygym-")
    for context in contexts:
        config = SimulationConfig.model_validate(
            {
                "placement": {
                    "mesh_asset_id": context["mesh_asset_id"],
                    "registration": context,
                }
            }
        )
        assert config.placement.registration.mesh_sha256 == context["mesh_sha256"]
        assert (
            SimulationConfig.model_validate_json(config.model_dump_json()).digest()
            == config.digest()
        )
