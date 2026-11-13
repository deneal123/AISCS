from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from service.application.population.contact_preflight import check_fragment_contacts
from service.domain.contracts.population.fragment import FragmentPopulationConfig
from service.infrastructure.execution.process import run_fragment_population_child
from tests.test_fragment_population_contract import example


def test_preflight_requires_audited_indexes_and_rejects_intersections(tmp_path, monkeypatch):
    config = FragmentPopulationConfig.model_validate(example())
    graph = SimpleNamespace(
        ids=np.array([10, 20]), provenance={"manifest_sha256": config.graph_manifest_sha256}
    )
    names = (
        "GENERATOR_MORPHOLOGY_BOUNDS_DB",
        "GENERATOR_MORPHOLOGY_BOUNDS_AUDIT",
        "GENERATOR_MORPHOLOGY_RADIUS_DB",
        "GENERATOR_MORPHOLOGY_RADIUS_AUDIT",
        "GENERATOR_MORPHOLOGY_SEGMENT_DB",
        "GENERATOR_MORPHOLOGY_SEGMENT_AUDIT",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="indexes are unavailable"):
        check_fragment_contacts(config, graph, [])
    for name in names:
        path = tmp_path / name
        path.touch()
        monkeypatch.setenv(name, str(path))
    captured = {}

    def screen(*args, **kwargs):
        captured["contacts"] = args[7]
        captured["clearance"] = args[8]
        return {
            "indexed": 2,
            "potential_intersections": [{"body_id": 10, "contact_indices": [0, 2]}],
        }

    monkeypatch.setattr("service.application.population.contact_preflight.screen_contacts", screen)
    with pytest.raises(ValueError, match="1 potential SWC intersections.*STIM\\+=1, E1=1"):
        check_fragment_contacts(config, graph, [])
    assert captured["contacts"] == [
        config.simulation.source_um,
        config.simulation.return_um,
        config.simulation.electrode_um,
        config.simulation.reference_um,
    ]
    assert captured["clearance"] == config.simulation.clearance_um
    monkeypatch.setattr(
        "service.application.population.contact_preflight.screen_contacts",
        lambda *args, **kwargs: {"indexed": 1, "potential_intersections": []},
    )
    with pytest.raises(ValueError, match="Incomplete contact-screen"):
        check_fragment_contacts(config, graph, [])
    monkeypatch.setattr(
        "service.application.population.contact_preflight.screen_contacts",
        lambda *args, **kwargs: {"indexed": 2, "potential_intersections": []},
    )
    assert check_fragment_contacts(config, graph, [])["indexed"] == 2
    graph.provenance["manifest_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="does not match"):
        check_fragment_contacts(config, graph, [])


def test_child_stops_before_loading_synapses_if_contact_screen_rejects(tmp_path, monkeypatch):
    monkeypatch.setenv("GENERATOR_SYNAPSE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "service.infrastructure.connectome.neighbors.registered_graph", lambda: object()
    )
    monkeypatch.setattr("service.settings.morphology_directories", lambda: [])

    def reject(*args):
        raise ValueError("Contact clearance not established")

    def unexpected(*args):
        raise AssertionError("Synapses loaded before contact screening")

    monkeypatch.setattr(
        "service.application.population.contact_preflight.check_fragment_contacts", reject
    )
    monkeypatch.setattr(
        "service.infrastructure.connectome.synapse_repository.registered_index", unexpected
    )
    with pytest.raises(ValueError, match="clearance"):
        run_fragment_population_child(
            {"execution_id": str(uuid4()), "config": example()}, str(tmp_path)
        )
    assert (tmp_path / "error.json").is_file()
    assert not (tmp_path / "manifest.json").exists()
