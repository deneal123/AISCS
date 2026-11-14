import copy
import hashlib
import json

import pytest

from service.application.feedback.fixed_inputs import (
    fixed_input_digest,
    fixed_input_factory,
    merge_fixed_input_schedules,
)


def fixture():
    provenance = {10: [], 20: [{'source_id': 10, 'candidate_index': 0}]}
    digest = hashlib.sha256(json.dumps({str(k): v for k, v in provenance.items()},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    schedule = {'graph_sha256': 'a' * 64, 'source_ids': [10, 20],
        'target_morphology_sha256': {20: 'c' * 64},
        'events_by_target': {10: [], 20: [{'child_node_id': 7}]},
        'provenance_by_target': provenance, 'provenance_sha256': digest,
        'event_count': 1, 'unresolved': []}
    return schedule, {10: 'b' * 64, 20: 'c' * 64}


def test_factory_freezes_inputs_and_restricts_batches():
    schedule, hashes = fixture()
    get = fixed_input_factory(schedule, [10, 20], hashes, graph_sha256='a' * 64,
                              expected_schedule_sha256=fixed_input_digest(schedule))
    schedule['events_by_target'][20][0]['child_node_id'] = 8
    output = get((20, 10))
    assert output == {20: [{'child_node_id': 7}], 10: []}
    output[20][0]['child_node_id'] = 9
    assert get((20,))[20][0]['child_node_id'] == 7
    with pytest.raises(ValueError, match='batch'):
        get((10, 10))
    with pytest.raises(ValueError, match='batch'):
        get((30,))


@pytest.mark.parametrize('mutation', ['graph', 'morphology', 'provenance', 'missing', 'partial'])
def test_factory_rejects_incompatible_schedules(mutation):
    schedule, hashes = fixture()
    broken = copy.deepcopy(schedule)
    if mutation == 'graph':
        broken['graph_sha256'] = 'd' * 64
    elif mutation == 'morphology':
        broken['target_morphology_sha256'][20] = 'd' * 64
    elif mutation == 'provenance':
        broken['provenance_by_target'][20][0]['source_id'] = 11
    elif mutation == 'missing':
        broken['events_by_target'].pop(10)
    else:
        broken['unresolved'] = [{}]
    with pytest.raises(ValueError):
        fixed_input_factory(broken, [10, 20], hashes, graph_sha256='a' * 64,
                            expected_schedule_sha256=fixed_input_digest(broken))


def test_factory_rejects_event_changed_after_schedule_digest():
    schedule, hashes = fixture()
    trusted = fixed_input_digest(schedule)
    schedule['events_by_target'][20][0]['child_node_id'] = 9
    with pytest.raises(ValueError, match='schedule digest'):
        fixed_input_factory(schedule, [10, 20], hashes, graph_sha256='a' * 64,
                            expected_schedule_sha256=trusted)


def test_merge_fixed_schedules_preserves_events_and_rejects_tampering():
    schedule, hashes = fixture()
    schedule['outside_window'] = 0
    digest = fixed_input_digest(schedule)
    merged = merge_fixed_input_schedules([(schedule, digest), (schedule, digest)],
        [10, 20], hashes, graph_sha256='a' * 64, max_events=2)
    assert merged['event_count'] == 2 and len(merged['events_by_target'][20]) == 2
    fixed_input_factory(merged, [10, 20], hashes, graph_sha256='a' * 64,
                        expected_schedule_sha256=fixed_input_digest(merged))
    schedule['events_by_target'][20][0]['child_node_id'] = 9
    with pytest.raises(ValueError, match='digest mismatch'):
        merge_fixed_input_schedules([(schedule, digest)], [10, 20], hashes,
                                    graph_sha256='a' * 64, max_events=2)
