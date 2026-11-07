import json
from copy import deepcopy

import pytest

from service.infrastructure.stimulation.feedback_discretization import (
    prepare_feedback_discretization,
)
from service.infrastructure.stimulation.feedback_discretization_archive import (
    _canonical,
    read_discretization_receipt,
    write_discretization_receipt,
)


def test_roundtrip_rechecks_inputs_and_rejects_mutation(tmp_path, monkeypatch):
    module = 'service.infrastructure.stimulation.feedback_discretization.'
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
    path = tmp_path / 'receipt.json'
    assert len(write_discretization_receipt(path, schedule, receipt, None, [], policy=policy)) == 64
    assert read_discretization_receipt(path, schedule, None, [], policy=policy) == receipt
    with pytest.raises(FileExistsError):
        write_discretization_receipt(path, schedule, receipt, None, [], policy=policy)
    changed = deepcopy(schedule)
    changed['events_by_target'][10][0]['time_ms'] = 4.
    with pytest.raises(ValueError, match='provenance mismatch'):
        read_discretization_receipt(path, changed, None, [], policy=policy)
    with pytest.raises(ValueError, match='provenance mismatch'):
        read_discretization_receipt(path, schedule, None, [], policy={**policy, 'max_nseg': 7})
    payload = json.loads(path.read_text(encoding='utf8'))
    payload['receipt']['targets']['10']['effective_events'][0]['time_ms'] = 9.
    path.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=False, allow_nan=False), encoding='utf8')
    with pytest.raises(ValueError, match='does not match verified inputs'):
        read_discretization_receipt(path, schedule, None, [], policy=policy)


def test_rejects_noncanonical_and_duplicate_json(tmp_path):
    path = tmp_path / 'invalid.json'
    path.write_text('{"format":"x","format":"x"}', encoding='utf8')
    with pytest.raises(ValueError, match='provenance mismatch'):
        read_discretization_receipt(path, {}, None, [], policy={})


def test_numeric_target_keys_have_stable_serialization_and_no_collisions():
    original = {'targets': {2: {'value': 2}, 10: {'value': 10}}}
    assert _canonical(json.loads(_canonical(original))) == _canonical(original)
    with pytest.raises(ValueError, match='Invalid discretization archive data'):
        _canonical({2: 1, '2': 2})
