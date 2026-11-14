from types import SimpleNamespace

import pytest

from service.application.feedback.lif_mapping import map_lif_feedback
from service.application.feedback.schedule import population_feedback_schedule


def test_spatial_index_is_explicitly_forwarded(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    seen = []

    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids,
                 use_spatial_index=False):
        seen.append(use_spatial_index)
        return {'body_id': str(target), 'direction': 'incoming',
                'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
                'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
                'candidates': [{'partner_id': '30', 'child_node_id': 9,
                                'segment_fraction': .5, 'source_position_8nm': [1, 2, 9],
                                'centerline_distance_um': 1.}]}

    monkeypatch.setattr('service.application.feedback.lif_mapping.'
                        'registered_incoming_candidates_single_pass', incoming)
    feedback = {'graph_sha256': 'a' * 64, 'events': [
        {'kind': 'lif-network-spike', 'source_id': 30, 'target_id': 20,
         'emission_tick_ms': 3, 'synapse_count': 1}]}
    normal = map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2)
    accelerated = map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2,
                                   experimental_spatial_index=True)
    assert seen == [False, True]
    assert accelerated == normal


def test_multiple_target_batches_preserve_all_mappings(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    batches = []
    def incoming_batch(_graph, targets):
        batches.append(targets.copy())
        return {body: [] for body in targets}
    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids,
                 use_spatial_index, _incoming_edges):
        assert use_spatial_index and _incoming_edges == [] and candidate_partner_ids == {1000}
        return {'body_id': str(target), 'direction': 'incoming',
                'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
                'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
                'candidates': [{'partner_id': '1000', 'child_node_id': 9,
                                'segment_fraction': .5, 'source_position_8nm': [1, 2, 9],
                                'centerline_distance_um': 1.}]}
    monkeypatch.setattr('service.infrastructure.connectome.neighbors.incoming_edge_indices_many',
                        incoming_batch)
    monkeypatch.setattr('service.application.feedback.lif_mapping.'
                        'registered_incoming_candidates_single_pass', incoming)
    targets = list(range(1, 66))
    feedback = {'graph_sha256': 'a' * 64, 'events': [
        {'kind': 'lif-network-spike', 'source_id': 1000, 'target_id': target,
         'emission_tick_ms': 3, 'synapse_count': 1} for target in targets]}
    cache = {}
    mappings = map_lif_feedback(graph, None, [], feedback, targets, max_distance_um=2,
                                experimental_spatial_index=True, _geometry_cache=cache)
    assert [len(batch) for batch in batches] == [64, 1]
    assert [row['target_id'] for row in mappings] == targets
    batches.clear()
    for event in feedback['events']:
        event['emission_tick_ms'] = 4
    cached = map_lif_feedback(graph, None, [], feedback, targets, max_distance_um=2,
                              experimental_spatial_index=True, _geometry_cache=cache)
    assert batches == []
    assert all(row['candidates'][0]['stimulated_ticks_ms'] == [4] for row in cached)
    cache.pop(next(key for key in cache if key[3] == 10))
    map_lif_feedback(graph, None, [], feedback, targets, max_distance_um=2,
                     experimental_spatial_index=True, _geometry_cache=cache)
    assert batches == [[10]]


def test_cached_batch_verifies_source_before_and_after(monkeypatch):
    class Index:
        def __init__(self):
            self.checks = 0

        def assert_unchanged(self):
            self.checks += 1
            if self.checks == 2:
                raise ValueError('source changed')

    monkeypatch.setattr('service.infrastructure.connectome.synapse_index.SynapseBatchIndex', Index)
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    index = Index()
    cache = {}
    events = []
    for target in (10, 20):
        events.append({'kind': 'lif-network-spike', 'source_id': 30, 'target_id': target,
                       'emission_tick_ms': 3, 'synapse_count': 1})
        cache[(id(graph), id(index), (), target, (30,))] = {
            'body_id': str(target), 'direction': 'incoming',
            'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
            'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
            'candidates': [{'partner_id': '30', 'child_node_id': 9,
                            'segment_fraction': .5, 'source_position_8nm': [1, 2, 9],
                            'centerline_distance_um': 1.}]}
    feedback = {'graph_sha256': 'a' * 64, 'events': events}
    with pytest.raises(ValueError, match='source changed'):
        map_lif_feedback(graph, index, [], feedback, [10, 20], max_distance_um=2,
                         experimental_spatial_index=True, _geometry_cache=cache)
    assert index.checks == 2


def test_large_batch_uses_reverse_index_once(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    calls = []

    class Reverse:
        def __init__(self, received):
            assert received is graph
            calls.append('built')

        def incoming(self, targets):
            calls.append(len(targets))
            return {target: [] for target in targets}

    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids,
                 use_spatial_index, _incoming_edges):
        assert use_spatial_index and _incoming_edges == [] and candidate_partner_ids == {2000}
        return {'body_id': str(target), 'direction': 'incoming',
                'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
                'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
                'candidates': [{'partner_id': '2000', 'child_node_id': 9,
                                'segment_fraction': .5, 'source_position_8nm': [1, 2, 9],
                                'centerline_distance_um': 1.}]}

    monkeypatch.setattr('service.infrastructure.connectome.reverse_edges.ReverseEdges', Reverse)
    monkeypatch.setattr('service.application.feedback.lif_mapping.'
                        'registered_incoming_candidates_single_pass', incoming)
    targets = list(range(1, 1025))
    feedback = {'graph_sha256': 'a' * 64, 'events': [
        {'kind': 'lif-network-spike', 'source_id': 2000, 'target_id': target,
         'emission_tick_ms': 3, 'synapse_count': 1} for target in targets]}
    result = map_lif_feedback(graph, None, [], feedback, targets, max_distance_um=2,
                              experimental_spatial_index=True)
    assert calls == ['built'] + [64] * 16
    assert [row['target_id'] for row in result] == targets


def test_lif_spikes_map_to_registered_target_candidates(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    event = {'kind': 'lif-network-spike', 'source_id': 30, 'target_id': 20,
             'emission_tick_ms': 3, 'delivery_tick_ms': 5, 'synapse_count': 2,
             'predicted_sign': 1, 'within_window': True, 'affects_replay': True}
    feedback = {'graph_sha256': 'a' * 64, 'delivery_delay_ms': 2, 'events': [event]}
    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids):
        assert target == 20 and candidate_partner_ids == {30}
        return {'body_id': '20', 'direction': 'incoming', 'graph_manifest_sha256': 'a' * 64,
                'complete_graph_edge_coverage': True, 'morphology_sha256': 'b' * 64,
                'source_md5': 'verified', 'candidates': [
                    {'partner_id': '30', 'child_node_id': child, 'segment_fraction': .5,
                     'source_position_8nm': [1, 2, child],
                     'presynaptic_position_8nm': [4, 5, child],
                     'centerline_distance_um': distance}
                    for child, distance in ((9, 1.), (10, 3.))]}
    module = 'service.application.feedback.lif_mapping.'
    monkeypatch.setattr(module + 'registered_incoming_candidates_single_pass', incoming)
    with pytest.raises(ValueError, match='Unresolved'):
        map_lif_feedback(graph, None, [], feedback, [10, 20], max_distance_um=2)
    mappings = map_lif_feedback(graph, None, [], feedback, [10, 20], max_distance_um=2,
                                allow_partial=True)
    assert len(mappings[0]['candidates']) == 1
    assert len(mappings[0]['unresolved_target_geometry']) == 1
    result = population_feedback_schedule([10, 20], feedback, mappings,
        {1: {'weight_us': .001, 'tau1_ms': .2, 'tau2_ms': 2., 'reversal_mv': 0.}},
        duration_ms=10, max_events=10, allow_partial_geometry=True)
    assert result['events_by_target'][20][0]['time_ms'] == 5
    assert result['provenance_by_target'][20][0]['source_position_8nm'] == [4, 5, 9]
    assert result['provenance_by_target'][20][0]['target_position_8nm'] == [1, 2, 9]
    assert result['event_count'] == 1 and len(result['unresolved']) == 1
    event['synapse_count'] = 3
    with pytest.raises(ValueError, match='coverage'):
        map_lif_feedback(graph, None, [], feedback, [10, 20], max_distance_um=2)


def test_geometry_cache_does_not_cache_spike_times_or_partner_sets(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    calls = []

    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids):
        calls.append(set(candidate_partner_ids))
        return {'body_id': str(target), 'direction': 'incoming',
                'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
                'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
                'candidates': [{'partner_id': str(partner), 'child_node_id': partner,
                    'segment_fraction': .5, 'source_position_8nm': [1, 2, partner],
                    'centerline_distance_um': 1.} for partner in candidate_partner_ids]}

    monkeypatch.setattr('service.application.feedback.lif_mapping.'
                        'registered_incoming_candidates_single_pass', incoming)
    feedback = {'graph_sha256': 'a' * 64, 'events': [
        {'kind': 'lif-network-spike', 'source_id': 30, 'target_id': 20,
         'emission_tick_ms': 3, 'synapse_count': 1}]}
    cache = {}
    def run():
        return map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2,
                                _geometry_cache=cache)

    assert run()[0]['candidates'][0]['stimulated_ticks_ms'] == [3]
    feedback['events'][0]['emission_tick_ms'] = 7
    assert run()[0]['candidates'][0]['stimulated_ticks_ms'] == [7]
    assert calls == [{30}]
    feedback['events'][0]['source_id'] = 31
    assert run()[0]['candidates'][0]['stimulated_ticks_ms'] == [7]
    assert calls == [{30}, {31}]


def test_geometry_cache_reuses_superset_without_reusing_event_times(monkeypatch):
    graph = SimpleNamespace(provenance={'manifest_sha256': 'a' * 64})
    calls = []

    def incoming(_index, _graph, target, _directories, *, candidate_partner_ids):
        calls.append(set(candidate_partner_ids))
        return {'body_id': str(target), 'direction': 'incoming',
                'graph_manifest_sha256': 'a' * 64, 'complete_graph_edge_coverage': True,
                'morphology_sha256': 'b' * 64, 'source_md5': 'verified',
                'candidates': [{'partner_id': str(partner), 'child_node_id': partner,
                    'segment_fraction': .5, 'source_position_8nm': [1, 2, partner],
                    'centerline_distance_um': 1.} for partner in sorted(candidate_partner_ids)]}

    monkeypatch.setattr('service.application.feedback.lif_mapping.'
                        'registered_incoming_candidates_single_pass', incoming)
    def event(source, tick):
        return {'kind': 'lif-network-spike', 'source_id': source, 'target_id': 20,
                'emission_tick_ms': tick, 'synapse_count': 1}
    feedback = {'graph_sha256': 'a' * 64, 'events': [event(30, 1), event(31, 2)]}
    cache = {}
    map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2,
                     _geometry_cache=cache)
    feedback['events'] = [event(31, 7)]
    cached = map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2,
                              _geometry_cache=cache)
    assert calls == [{30, 31}]
    uncached = map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2)
    assert cached == uncached
    assert cached[0]['candidates'][0]['stimulated_ticks_ms'] == [7]
    feedback['events'][0]['synapse_count'] = 2
    with pytest.raises(ValueError, match='coverage'):
        map_lif_feedback(graph, None, [], feedback, [20], max_distance_um=2,
                         _geometry_cache=cache)
