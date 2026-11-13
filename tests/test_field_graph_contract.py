import copy

import pytest
from pydantic import ValidationError

from service.domain.contracts.field.graph import FieldGraphConfig


def payload():
    return {
        "graph_manifest_sha256": "a" * 64,
        "source_cells": [{"body_id": 10, "child_node_id": 2, "threshold_mv": -20.0}],
        "replay_ids": [20],
        "seed": 1,
        "simulation": {
            "source_um": [0, 0, 0],
            "return_um": [100, 0, 0],
            "electrode_um": [0, 50, 0],
            "reference_um": [100, 50, 0],
            "current_na": 1000,
            "conductivity_s_m": 0.3,
            "clearance_um": 1,
            "duration_ms": 10,
            "dt_ms": 0.05,
            "pulse_start_ms": 2,
            "pulse_end_ms": 3,
            "rise_time_ms": 0.2,
            "interphase_gap_ms": 0,
            "pulse_shape": "monophasic",
            "nseg_per_edge": 1,
            "allow_disconnected": False,
            "source_model": "pointsource",
            "coordinate_frame": "male-cns-v1.0-native-um",
        },
        "synapse": {
            "delay_ms": 2,
            "weight_us": 0.001,
            "tau1_ms": 0.2,
            "tau2_ms": 2,
            "reversal_mv": 0,
        },
        "acquisition": {"low_hz": 100, "high_hz": 3000, "recovery_ms": 0.5, "clip_uv": None},
    }


def test_contract_preserves_configuration_and_explicit_optional_clip():
    first = FieldGraphConfig.model_validate(payload())
    second = FieldGraphConfig.model_validate(copy.deepcopy(payload()))
    assert first.digest() == second.digest()
    assert "retain_currents" not in first.model_dump(mode="json")
    plan = first.execution_parameters()
    assert plan["acquisition"]["clip_uv"] is None
    assert plan["recording"]["source_model"] == "pointsource"
    assert (
        plan["simulation_parameters"]["duration_ms"] == plan["schedule_parameters"]["duration_ms"]
    )


def test_spatial_morphology_digest_is_opt_in_and_changes_identity():
    raw = payload()
    original = FieldGraphConfig.model_validate(raw)
    assert 'morphology_sha256' not in original.model_dump(mode='json')['source_cells'][0]
    raw['source_cells'][0]['morphology_sha256'] = 'b' * 64
    bound = FieldGraphConfig.model_validate(raw)
    assert bound.digest() != original.digest()
    assert bound.execution_parameters()['source_cells'][0]['morphology_sha256'] == 'b' * 64
    raw['source_cells'][0]['morphology_sha256'] = 'invalid'
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)


def test_archive_is_opt_in_and_changes_configuration_identity():
    raw = payload()
    original = FieldGraphConfig.model_validate(raw)
    raw["retain_currents"] = True
    archived = FieldGraphConfig.model_validate(raw)
    assert archived.retain_currents is True
    assert archived.digest() != original.digest()
    raw["retain_currents"] = 1
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)


def test_state_contrast_is_explicit_and_preserves_legacy_digest():
    raw = payload()
    initial = FieldGraphConfig.model_validate(raw)
    assert 'retain_state_contrast' not in initial.model_dump(mode='json')
    raw['retain_state_contrast'] = True
    selected = FieldGraphConfig.model_validate(raw)
    assert selected.digest() != initial.digest()
    raw['retain_state_contrast'] = 1
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)


def test_compartment_crossing_archive_is_explicit_and_preserves_legacy_digest():
    raw = payload()
    initial = FieldGraphConfig.model_validate(raw)
    assert 'retain_compartment_crossings' not in initial.model_dump(mode='json')
    assert 'retain_compartment_crossings' not in initial.execution_parameters()
    raw['retain_compartment_crossings'] = True
    selected = FieldGraphConfig.model_validate(raw)
    assert selected.digest() != initial.digest()
    assert selected.execution_parameters()['retain_compartment_crossings'] is True
    raw['retain_compartment_crossings'] = 1
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)


def test_pulse_train_is_explicit_validated_and_preserves_old_configurations():
    raw = payload()
    old = FieldGraphConfig.model_validate(raw)
    assert 'pulse_count' not in old.model_dump(mode='json')['simulation']
    assert 'pulse_count' not in old.execution_parameters()['simulation_parameters']
    raw['simulation']['duration_ms'] = 20.
    raw['simulation']['pulse_count'] = 2
    raw['simulation']['pulse_interval_ms'] = 5.
    train = FieldGraphConfig.model_validate(raw)
    assert train.execution_parameters()['simulation_parameters']['pulse_count'] == 2
    assert train.digest() != old.digest()
    for update in ({'pulse_count': 1}, {'pulse_interval_ms': 1.},
                   {'pulse_interval_ms': None}, {'pulse_count': True}):
        broken = copy.deepcopy(raw)
        broken['simulation'].update(update)
        with pytest.raises(ValidationError):
            FieldGraphConfig.model_validate(broken)


@pytest.mark.parametrize(
    "field,value",
    [("replay_ids", [True]), ("replay_ids", [10]), ("replay_ids", [20, 20]), ("seed", True)],
)
def test_contract_rejects_malformed_and_overlapping_cells(field, value):
    raw = payload()
    raw[field] = value
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)


def test_contract_rejects_non_integer_duration_and_invalid_bandwidth():
    raw = payload()
    raw["simulation"]["duration_ms"] = 10.5
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)
    raw = payload()
    raw["acquisition"]["high_hz"] = 10000
    with pytest.raises(ValidationError):
        FieldGraphConfig.model_validate(raw)
