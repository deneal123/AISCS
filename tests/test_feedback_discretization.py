from copy import deepcopy

import pytest

from service.infrastructure.stimulation.feedback.discretization import (
    prepare_feedback_discretization,
    prepare_shared_feedback_discretization,
    prepare_uniform_feedback_replays,
    verify_feedback_discretization,
)


def test_shared_feedback_checks_both_conditions_and_target_identity(monkeypatch):
    from service.application.feedback.fixed_inputs import fixed_input_digest

    module = 'service.infrastructure.stimulation.feedback.discretization.'
    audits = []
    monkeypatch.setattr(module + 'audit_feedback_observations',
                        lambda schedule, *_a, **_k: audits.append(schedule) or {'verified': True})
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'body_id': '10', 'sha256': 'a' * 64,
        'swc': '1 1 0 0 0 1 -1\n2 3 125 0 0 1 1\n3 3 250 0 0 1 2\n'})
    origin = {'source_position_8nm': [1, 2, 3], 'target_position_8nm': [125, 0, 0]}
    base = {'graph_sha256': 'c' * 64, 'source_ids': [10],
            'target_morphology_sha256': {10: 'a' * 64},
            'events_by_target': {10: [{'child_node_id': 2, 'position': 1.}]},
            'provenance_by_target': {10: [origin]}}
    control = deepcopy(base)
    control['events_by_target'][10] = []
    control['provenance_by_target'][10] = []
    conditions = {'control': (control, fixed_input_digest(control)),
                  'stimulated': (base, fixed_input_digest(base))}
    options = {'expected_source_md5': 'b' * 32, 'max_shift_um': .1,
               'max_observation_distance_um': .2, 'max_nseg': 9}
    result = prepare_shared_feedback_discretization(conditions, None, [], **options)
    assert len(audits) == 2
    assert result['restart_required']
    assert result['targets'][10]['fixed']['nseg_by_edge'] == {'2': 5}
    assert result['targets'][10]['fixed']['conditions']['control']['effective_events'] == []
    active = result['targets'][10]['fixed']['conditions']['stimulated']['effective_events']
    assert active[0]['position'] == .9
    repeated = prepare_shared_feedback_discretization(conditions, None, [],
        previous_grids={10: {'2': 5}}, **options)
    assert not repeated['restart_required']
    assert repeated['targets'][10]['fixed']['nseg_by_edge'] == {'2': 5}
    uniform = prepare_shared_feedback_discretization(conditions, None, [], uniform=True, **options)
    assert uniform['targets'][10]['fixed']['nseg_by_edge'] == {'2': 5, '3': 5}
    assert uniform['targets'][10]['fixed']['conditions']['stimulated']['effective_events'][0][
        'position'] == .9
    repeated_uniform = prepare_shared_feedback_discretization(conditions, None, [], uniform=True,
        previous_grids={10: {'2': 5, '3': 5}}, **options)
    assert not repeated_uniform['restart_required']
    paired = prepare_uniform_feedback_replays(conditions, None, [], **options)
    assert paired['nseg_by_body'] == {10: 5}
    assert paired['conditions']['stimulated']['schedule']['events_by_target'][10][0][
        'position'] == .9
    assert base['events_by_target'][10][0]['position'] == 1.
    assert paired['conditions']['stimulated']['original_sha256'] == fixed_input_digest(base)
    assert paired['conditions']['stimulated']['sha256'] != fixed_input_digest(base)
    altered = deepcopy(base)
    altered['target_morphology_sha256'][10] = 'f' * 64
    with pytest.raises(ValueError, match='morphology mismatch'):
        prepare_shared_feedback_discretization({**conditions,
            'stimulated': (altered, fixed_input_digest(altered))}, None, [], **options)


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
