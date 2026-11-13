from copy import deepcopy

import pytest

from service.infrastructure.stimulation.feedback.observation_audit import (
    audit_feedback_observations,
)


def example(monkeypatch):
    module = 'service.infrastructure.stimulation.feedback.observation_audit.'
    monkeypatch.setattr(module + 'read_skeleton', lambda *_a, **_k: {
        'body_id': '20', 'sha256': 'a' * 64, 'swc': 'verified'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda _swc, points: {
        'child_node_ids': [7] * len(points), 'segment_fractions': [1.] * len(points),
        'centerline_distances_um': [.075] * len(points)})

    class Index:
        def query(self, target, direction, *, limit, partner_ids):
            assert (target, direction, limit, partner_ids) == (20, 'incoming', None, [10])
            return {'truncated': False, 'source_md5': 'b' * 32, 'total': 1, 'returned': 1,
                    'pairs': [{'body_pre': 10, 'body_post': 20,
                               'x_pre': 10, 'y_pre': 20, 'z_pre': 30,
                               'x_post': 100, 'y_post': 200, 'z_post': 300}]}
    event = {'child_node_id': 7, 'position': 1.}
    origin = {'source_id': 10, 'source_tick_ms': 3,
              'target_position_8nm': [100, 200, 300], 'target_distance_um': .075}
    return {'events_by_target': {20: [event]}, 'provenance_by_target': {20: [origin]},
            'target_morphology_sha256': {20: 'a' * 64}}, Index()


def test_audit_checks_index_and_projection(monkeypatch):
    schedule, index = example(monkeypatch)
    assert audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)[
        'verified_events'] == 1
    bad = deepcopy(schedule)
    bad['provenance_by_target'][20][0]['target_position_8nm'][0] = 101
    with pytest.raises(ValueError, match='absent from indexed'):
        audit_feedback_observations(bad, index, [], expected_source_md5='b' * 32)
    bad = deepcopy(schedule)
    bad['events_by_target'][20][0]['position'] = .9
    with pytest.raises(ValueError, match='projection mismatch'):
        audit_feedback_observations(bad, index, [], expected_source_md5='b' * 32)


def test_repeated_events_cannot_duplicate_one_synapse_per_tick(monkeypatch):
    schedule, index = example(monkeypatch)
    schedule['events_by_target'][20] *= 2
    schedule['provenance_by_target'][20] *= 2
    with pytest.raises(ValueError, match='absent from indexed'):
        audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)


def test_source_and_target_coordinates_must_identify_same_synapse(monkeypatch):
    schedule, index = example(monkeypatch)
    origin = schedule['provenance_by_target'][20][0]
    origin['source_position_8nm'] = [10, 20, 30]
    assert audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)[
        'verified_events'] == 1
    origin['source_position_8nm'] = [11, 20, 30]
    with pytest.raises(ValueError, match='source-target observation'):
        audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)


def test_one_verified_morphology_snapshot_is_reused_for_same_target(monkeypatch):
    schedule, _ = example(monkeypatch)
    first = schedule['provenance_by_target'][20][0]
    schedule['events_by_target'][20].append(schedule['events_by_target'][20][0].copy())
    schedule['provenance_by_target'][20].append({**first, 'source_id': 11})
    reads = []
    monkeypatch.setattr('service.infrastructure.stimulation.feedback.observation_audit.read_skeleton',
                        lambda body, _dirs, **_kw: reads.append(body) or {
                            'body_id': '20', 'sha256': 'a' * 64, 'swc': 'verified'})

    class Index:
        def query(self, _target, _direction, *, limit, partner_ids):
            assert partner_ids == [10, 11]
            return {'truncated': False, 'source_md5': 'b' * 32, 'total': 2, 'returned': 2,
                    'pairs': [{'body_pre': source, 'body_post': 20,
                               'x_post': 100, 'y_post': 200, 'z_post': 300}
                              for source in partner_ids]}

    result = audit_feedback_observations(schedule, Index(), [], expected_source_md5='b' * 32)
    assert result['verified_events'] == 2
    assert reads == [20]


def test_projection_is_batched_by_target_without_losing_pair_checks(monkeypatch):
    schedule, _ = example(monkeypatch)
    origin = schedule['provenance_by_target'][20][0]
    schedule['events_by_target'][20].append({'child_node_id': 8, 'position': .5})
    schedule['provenance_by_target'][20].append({**origin, 'source_id': 11,
                                                 'target_position_8nm': [200, 200, 300],
                                                 'target_distance_um': .15})
    calls = []

    def map_once(_swc, points):
        calls.append(points)
        return {'child_node_ids': [7, 8], 'segment_fractions': [1., .5],
                'centerline_distances_um': [.075, .15]}

    class Index:
        def query(self, _target, _direction, *, limit, partner_ids):
            assert limit is None and partner_ids == [10, 11]
            rows = [{'body_pre': source, 'body_post': 20, 'x_post': x,
                     'y_post': 200, 'z_post': 300} for source, x in [(10, 100), (11, 200)]]
            return {'truncated': False, 'source_md5': 'b' * 32, 'total': 2, 'returned': 2,
                    'pairs': rows}

    monkeypatch.setattr('service.infrastructure.stimulation.feedback.observation_audit.'
                        'map_fragment_candidates', map_once)
    assert audit_feedback_observations(schedule, Index(), [], expected_source_md5='b' * 32)[
        'verified_events'] == 2
    assert calls == [[[.8, 1.6, 2.4], [1.6, 1.6, 2.4]]]
    bad = deepcopy(schedule)
    bad['events_by_target'][20][1]['child_node_id'] = 7
    with pytest.raises(ValueError, match='projection mismatch'):
        audit_feedback_observations(bad, Index(), [], expected_source_md5='b' * 32)


def test_source_queries_are_bounded_and_reject_unrequested_pairs(monkeypatch):
    schedule, _ = example(monkeypatch)
    event = schedule['events_by_target'][20][0]
    origin = schedule['provenance_by_target'][20][0]
    schedule['events_by_target'][20] = [event.copy() for _ in range(21)]
    schedule['provenance_by_target'][20] = [
        {**origin, 'source_id': source} for source in range(100, 121)]
    calls = []

    class Index:
        wrong_source = False

        def query(self, target, direction, *, limit, partner_ids):
            assert (target, direction, limit) == (20, 'incoming', None)
            calls.append(partner_ids)
            rows = [{'body_pre': source, 'body_post': target,
                     'x_post': 100, 'y_post': 200, 'z_post': 300}
                    for source in partner_ids]
            if self.wrong_source:
                rows[0]['body_pre'] = 999
            return {'truncated': False, 'source_md5': 'b' * 32, 'total': len(rows),
                    'returned': len(rows), 'pairs': rows}

    index = Index()
    result = audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)
    assert result['verified_events'] == 21
    assert [len(row) for row in calls] == [20, 1]
    index.wrong_source = True
    with pytest.raises(ValueError, match='pair mismatch'):
        audit_feedback_observations(schedule, index, [], expected_source_md5='b' * 32)
