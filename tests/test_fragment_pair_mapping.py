from types import SimpleNamespace

import pytest

from service.infrastructure.stimulation.fragment_pair_mapping import (
    match_fragment_inputs,
    schedule_matched_fragment_events,
    schedule_population_fragment_events,
)


def test_matching_requires_exact_unique_indexed_pairs_and_target_geometry(monkeypatch):
    row = {'body_pre': 10, 'body_post': 20, 'x_pre': 1, 'y_pre': 2, 'z_pre': 3,
           'x_post': 4, 'y_post': 5, 'z_post': 6}
    source = {'included_in_graph': True, 'partner_id': '20', 'source_position_8nm': [1, 2, 3],
              'stimulated_ticks_ms': [1], 'centerline_distance_um': .1}
    diagnostic = {'source_md5': 'verified', 'candidates': [source]}
    graph = SimpleNamespace(posts=[0], provenance={'manifest_sha256': 'a' * 64})
    index = SimpleNamespace(query=lambda *_a, **_kw: {
        'pairs': [row], 'truncated': False, 'source_md5': 'verified', 'total': 1, 'returned': 1})
    module = 'service.infrastructure.stimulation.fragment_pair_mapping.'
    monkeypatch.setattr(module + 'fragment_edge_schedule', lambda *_a, **_kw: {
        'source_id': 10, 'graph_sha256': 'a' * 64})
    monkeypatch.setattr(module + 'outgoing', lambda *_a: {
        'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 1}]})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a: {'swc': 'verified', 'sha256': 'b' * 64, 'body_id': '20'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9], 'segment_fractions': [.5], 'centerline_distances_um': [.1]})
    def match():
        return match_fragment_inputs(diagnostic, index, graph, 20, [], max_source_distance_um=2,
                                     max_target_distance_um=2, duration_ms=3)
    result = match()
    assert result['candidates'][0]['target_position_8nm'] == [4, 5, 6]
    assert result['candidates'][0]['stimulated_ticks_ms'] == [1]
    scheduled = schedule_matched_fragment_events(result, delay_ms=1, duration_ms=3, weight_us=.01,
                                                tau1_ms=.2, tau2_ms=2, reversal_mv=0, max_events=10)
    assert scheduled['evidence'][0]['source_position_8nm'] == [1, 2, 3]
    assert scheduled['evidence'][0]['target_position_8nm'] == [4, 5, 6]
    row['x_pre'] = 9
    with pytest.raises(ValueError, match='Ambiguous source coordinates'):
        match()
    row['x_pre'] = 1
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9], 'segment_fractions': [.5], 'centerline_distances_um': [2.1]})
    with pytest.raises(ValueError, match='Unresolved target geometry'):
        match()
    partial = match_fragment_inputs(diagnostic, index, graph, 20, [], max_source_distance_um=2,
                                    max_target_distance_um=2, duration_ms=3, allow_partial=True)
    assert partial['candidates'] == []
    assert partial['unresolved_target_geometry'][0]['stimulated_ticks_ms'] == [1]
    with pytest.raises(ValueError, match='Invalid matched replay parameters'):
        schedule_matched_fragment_events(partial, delay_ms=1, duration_ms=3, weight_us=.01,
                                         tau1_ms=.2, tau2_ms=2, reversal_mv=0, max_events=10)
    source['centerline_distance_um'] = 2.1
    partial_source = match_fragment_inputs(diagnostic, index, graph, 20, [],
        max_source_distance_um=2, max_target_distance_um=2, duration_ms=3,
        allow_partial_source=True)
    assert partial_source['candidates'] == []
    assert partial_source['unresolved_source_geometry'] == [{'source_position_8nm': [1, 2, 3],
        'target_position_8nm': [4, 5, 6], 'source_distance_um': 2.1}]
    with pytest.raises(ValueError, match='Invalid matched replay parameters'):
        schedule_matched_fragment_events(partial_source, delay_ms=1, duration_ms=3, weight_us=.01,
                                         tau1_ms=.2, tau2_ms=2, reversal_mv=0, max_events=10)


def test_matching_preserves_synapses_with_identical_presynaptic_coordinates(monkeypatch):
    rows = [{'body_pre': 10, 'body_post': 20, 'x_pre': 1, 'y_pre': 2, 'z_pre': 3,
             'x_post': x, 'y_post': 5, 'z_post': 6} for x in (4, 8)]
    candidate = {'included_in_graph': True, 'partner_id': '20', 'source_position_8nm': [1, 2, 3],
        'child_node_id': 7, 'result_segment_index': 0, 'segment_fraction': .5,
        'centerline_distance_um': .1, 'status': 'stimulus_only_crossing',
        'stimulated_ticks_ms': [1], 'control_ticks_ms': []}
    diagnostic = {'body_id': '10', 'graph_sha256': 'a' * 64, 'simulation_sha256': 'c' * 64,
        'source_md5': 'verified', 'threshold_mv': -20., 'duration_ms': 4,
        'source_pairs': 2, 'graph_pairs': 2, 'candidates': [candidate.copy(), candidate.copy()]}
    graph = SimpleNamespace(posts=[0], provenance={'manifest_sha256': 'a' * 64})
    index = SimpleNamespace(query=lambda *_a, **_k: {
        'pairs': rows, 'truncated': False, 'source_md5': 'verified', 'total': 2, 'returned': 2})
    module = 'service.infrastructure.stimulation.fragment_pair_mapping.'
    monkeypatch.setattr(module + 'outgoing', lambda *_a: {
        'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a: {'swc': 'verified', 'sha256': 'b' * 64, 'body_id': '20'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9, 10], 'segment_fractions': [.5, .5],
        'centerline_distances_um': [.1, .1]})
    def match():
        return match_fragment_inputs(diagnostic, index, graph, 20, [], max_source_distance_um=2,
                                     max_target_distance_um=2, duration_ms=4)
    result = match()
    assert [row['target_child_node_id'] for row in result['candidates']] == [9, 10]
    assert [row['stimulated_ticks_ms'] for row in result['candidates']] == [[1], [1]]
    diagnostic['candidates'][1]['result_segment_index'] = 1
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        match()


def test_schedule_only_uses_each_candidates_own_ticks_and_explicit_kinetics():
    mapping = {'candidates': [
        {'target_child_node_id': 9, 'target_fraction': .5, 'stimulated_ticks_ms': [1, 4]},
        {'target_child_node_id': 8, 'target_fraction': .2, 'stimulated_ticks_ms': [2]},
    ]}
    kwargs = {'delay_ms': 1, 'duration_ms': 5, 'weight_us': .01, 'tau1_ms': .2,
              'tau2_ms': 2, 'reversal_mv': 0, 'max_events': 10}
    result = schedule_matched_fragment_events(mapping, **kwargs)
    assert [(event['child_node_id'], event['time_ms']) for event in result['events']] == [
        (9, 2), (8, 3)]
    assert result['outside_window'] == 1
    with pytest.raises(ValueError, match='event limit'):
        schedule_matched_fragment_events(mapping, **{**kwargs, 'max_events': 1})


def test_upper_bound_sensitivity_is_explicit_and_requires_verified_intervals():
    mapping = {'candidates': [{'target_child_node_id': 9, 'target_fraction': .5,
        'stimulated_ticks_ms': [4],
        'stimulated_crossing_intervals': [{'lower_ms': 3.1, 'upper_ms': 3.15, 'tick_ms': 4}]}]}
    kwargs = {'delay_ms': 1, 'duration_ms': 10, 'weight_us': .01, 'tau1_ms': .2,
              'tau2_ms': 2, 'reversal_mv': 0, 'max_events': 10}
    tick = schedule_matched_fragment_events(mapping, **kwargs)
    bound = schedule_matched_fragment_events(mapping, **kwargs, timing_mode='upper_bound')
    lower = schedule_matched_fragment_events(mapping, **kwargs, timing_mode='lower_bound')
    assert tick['events'][0]['time_ms'] == 5
    assert bound['events'][0]['time_ms'] == pytest.approx(4.15)
    assert lower['events'][0]['time_ms'] == pytest.approx(4.1)
    assert lower['timing_mode'] == 'lower_bound'
    assert bound['evidence'][0]['source_interval']['lower_ms'] == 3.1
    with pytest.raises(ValueError, match='interval count'):
        schedule_matched_fragment_events(
            {'candidates': [{k: v for k, v in mapping['candidates'][0].items()
                             if k != 'stimulated_crossing_intervals'}]},
            **kwargs, timing_mode='upper_bound')


def test_population_schedule_preserves_source_identity_and_rejects_partial_results():
    def mapping(source, tick):
        return {'source_id': source, 'target_id': 20, 'graph_sha256': 'a' * 64,
                'target_morphology_sha256': 'b' * 64,
                'candidates': [{'target_child_node_id': source, 'target_fraction': .5,
                                'stimulated_ticks_ms': [tick]}]}
    params = {'delay_ms': 0, 'duration_ms': 5, 'weight_us': .01, 'tau1_ms': .2,
              'tau2_ms': 2, 'reversal_mv': 0}
    mappings = [mapping(10, 1), mapping(11, 2)]
    result = schedule_population_fragment_events(mappings, [params, params], max_events=2)
    assert result['source_ids'] == [10, 11]
    assert [row['source_id'] for row in result['evidence']] == [10, 11]
    assert [row['time_ms'] for row in result['events']] == [1, 2]
    with pytest.raises(ValueError, match='event limit'):
        schedule_population_fragment_events(mappings, [params, params], max_events=1)
    with pytest.raises(ValueError, match='Incompatible population'):
        schedule_population_fragment_events([mappings[0], mappings[0]], [params, params],
                                            max_events=2)
    with pytest.raises(ValueError, match='Incompatible population'):
        altered = {**mappings[1], 'target_morphology_sha256': 'c' * 64}
        schedule_population_fragment_events([mappings[0], altered], [params, params], max_events=2)
    with pytest.raises(ValueError, match='durations differ'):
        schedule_population_fragment_events(mappings, [params, {**params, 'duration_ms': 6}],
                                            max_events=2)
