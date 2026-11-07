import json
from pathlib import Path

import pytest

from service.contracts import SimulationConfig
from service.domain.catalog import catalog
from service.domain.surface_anchors import validate_surface_anchors


def anchored_config():
    payload = catalog()["models"][1]["defaults"]
    source = json.loads(
        (
            Path(__file__).resolve().parents[1] / "service/domain/flybody-external-contacts.json"
        ).read_text()
    )
    payload["placement"]["registration"]["surface_anchors"] = {
        name: {
            "contact": name,
            "mesh_part": source["mesh_part"],
            "triangle": row["triangle"],
            "barycentric": row["barycentric"],
        }
        for name, row in source["contacts"].items()
    }
    return payload


def test_real_surface_contacts_match_source_triangles():
    validate_surface_anchors(SimulationConfig.model_validate(anchored_config()))


@pytest.mark.parametrize("name", ["electrode", "reference"])
def test_moved_contact_or_changed_anchor_is_rejected(name):
    payload = anchored_config()
    payload["placement"][name]["x_um"] += 1
    with pytest.raises(ValueError, match="coordinates do not match"):
        validate_surface_anchors(SimulationConfig.model_validate(payload))


def test_legacy_record_without_per_contact_anchors_remains_readable():
    payload = anchored_config()
    payload["placement"]["registration"].pop("surface_anchors")
    validate_surface_anchors(SimulationConfig.model_validate(payload))
