from types import SimpleNamespace

import pytest

from service.application.feedback.lif_feedback_mapping import map_lif_feedback
from service.application.feedback.population_feedback_schedule import population_feedback_schedule


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
    module = 'service.application.feedback.lif_feedback_mapping.'
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

    monkeypatch.setattr('service.application.feedback.lif_feedback_mapping.'
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

    monkeypatch.setattr('service.application.feedback.lif_feedback_mapping.'
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
