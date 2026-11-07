from copy import deepcopy

import pytest
from pydantic import ValidationError

from service.domain.contracts.fragment_population_contract import FragmentPopulationConfig
from tests.test_field_graph_contract import payload


def example():
    simulation = deepcopy(payload()["simulation"])
    simulation["allow_disconnected"] = True
    return {
        "graph_manifest_sha256": "a" * 64,
        "source_ids": [10, 20],
        "seed": 1,
        "simulation": simulation,
        "threshold_mv": -20.0,
        "max_distance_um": 2.0,
    }


def test_fragment_population_configuration_is_path_free_and_deterministic():
    first = FragmentPopulationConfig.model_validate(example())
    assert first.digest() == FragmentPopulationConfig.model_validate(deepcopy(example())).digest()
    arguments = first.execution_parameters()
    assert arguments["source_ids"] == [10, 20]
    assert arguments["simulation_parameters"]["allow_disconnected"] is True
    assert "electrode_um" not in arguments["simulation_parameters"]
    assert arguments["electrode_um"] == [0.0, 50.0, 0.0]
    other = example()
    other["max_distance_um"] = 1.0
    assert first.digest() != FragmentPopulationConfig.model_validate(other).digest()


def test_partial_geometry_is_explicit_and_preserves_legacy_identity():
    legacy = FragmentPopulationConfig.model_validate(example())
    assert 'allow_partial_geometry' not in legacy.model_dump(mode='json')
    assert 'allow_partial_geometry' not in legacy.execution_parameters()
    partial = FragmentPopulationConfig.model_validate({**example(), 'allow_partial_geometry': True})
    assert partial.execution_parameters()['allow_partial_geometry'] is True
    assert partial.digest() != legacy.digest()
    with pytest.raises(ValidationError):
        FragmentPopulationConfig.model_validate({**example(), 'allow_partial_geometry': 'true'})


@pytest.mark.parametrize(
    "change",
    [
        {"source_ids": [True]},
        {"source_ids": [10, 10]},
        {"source_ids": []},
        {"source_ids": list(range(1, 258))},
        {"max_distance_um": -1},
        {"threshold_mv": float("nan")},
        {"graph_manifest_sha256": "invalid"},
    ],
)
def test_invalid_fragment_configs_rejected(change):
    with pytest.raises(ValidationError):
        FragmentPopulationConfig.model_validate({**example(), **change})


@pytest.mark.parametrize(
    "change",
    [
        {"allow_disconnected": False},
        {"duration_ms": 10.5},
    ],
)
def test_fragment_mode_rejects_unsupported_stimulus(change):
    data = example()
    data["simulation"].update(change)
    with pytest.raises(ValidationError):
        FragmentPopulationConfig.model_validate(data)


def test_zero_current_control_is_valid_and_has_distinct_identity():
    data = example()
    stimulated = FragmentPopulationConfig.model_validate(data)
    data['simulation']['current_na'] = 0.0
    control = FragmentPopulationConfig.model_validate(data)
    assert control.execution_parameters()['simulation_parameters']['current_na'] == 0.0
    assert control.digest() != stimulated.digest()
