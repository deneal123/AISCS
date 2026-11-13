from copy import deepcopy

import pytest

from service.infrastructure.stimulation.feedback.discretization import (
    prepare_feedback_discretization,
    verify_feedback_discretization,
)


def test_prepares_verified_feedback_without_modifying_schedule(monkeypatch):
    module = 'service.infrastructure.stimulation.feedback.discretization.'
    monkeypatch.setattr(module + 'audit_feedback_observations',
                        lambda *_a, **_k: {'verified_events': 1})
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'swc': '1 1 0 0 0 1 -1\n2 3 750 0 0 1 1\n'})
    event = {'child_node_id': 2, 'position': 1., 'time_ms': 2.}
    origin = {'source_position_8nm': [1, 2, 3], 'target_position_8nm': [750, 0, 0]}
    schedule = {'events_by_target': {10: [event]}, 'provenance_by_target': {10: [origin]},
                'target_morphology_sha256': {10: 'a' * 64}}
    before = deepcopy(schedule)
    result = prepare_feedback_discretization(
        schedule, None, [], expected_source_md5='b' * 32, max_shift_um=1.,
        max_observation_distance_um=2., max_nseg=5)
    assert schedule == before
    assert result['observation_audit']['verified_events'] == 1
    assert result['targets'][10]['effective_events'][0]['position'] == pytest.approx(5/6)
    assert result['targets'][10]['nseg_by_edge'] == {'2': 3}


def test_refuses_legacy_events_without_source_coordinates(monkeypatch):
    module = 'service.infrastructure.stimulation.feedback.discretization.'
    monkeypatch.setattr(module + 'audit_feedback_observations', lambda *_a, **_k: {})
    schedule = {'events_by_target': {10: [{'child_node_id': 2, 'position': 1.}]},
                'provenance_by_target': {10: [{'target_position_8nm': [750, 0, 0]}]}}
    with pytest.raises(ValueError, match='Both source and target'):
        prepare_feedback_discretization(schedule, None, [], expected_source_md5='b' * 32,
            max_shift_um=1., max_observation_distance_um=2., max_nseg=5)


def test_receipt_is_rebuilt_from_source_and_explicit_policy(monkeypatch):
    module = 'service.infrastructure.stimulation.feedback.discretization.'
    monkeypatch.setattr(module + 'audit_feedback_observations',
                        lambda *_a, **_k: {'verified_events': 1})
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'swc': '1 1 0 0 0 1 -1\n2 3 750 0 0 1 1\n'})
    schedule = {'events_by_target': {10: [{'child_node_id': 2, 'position': 1., 'time_ms': 2.}]},
                'provenance_by_target': {10: [{'source_position_8nm': [1, 2, 3],
                                                'target_position_8nm': [750, 0, 0]}]},
                'target_morphology_sha256': {10: 'a' * 64}}
    policy = {'expected_source_md5': 'b' * 32, 'max_shift_um': 1.,
              'max_observation_distance_um': 2., 'max_nseg': 5}
    receipt = prepare_feedback_discretization(schedule, None, [], **policy)
    assert verify_feedback_discretization(schedule, receipt, None, [], policy=policy) == receipt
    altered = deepcopy(receipt)
    altered['targets'][10]['effective_events'][0]['time_ms'] = 3.
    with pytest.raises(ValueError, match='does not match'):
        verify_feedback_discretization(schedule, altered, None, [], policy=policy)
    with pytest.raises(ValueError, match='does not match'):
        verify_feedback_discretization(schedule, receipt, None, [],
                                       policy={**policy, 'max_nseg': 7})
