import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from service.application.feedback.schedule import (
    combine_partial_feedback_schedules,
    population_feedback_schedule,
)
from service.infrastructure.stimulation.experimental_gpu.events import (
    feedback_midpoint_events,
    feedback_refined_events,
)
from service.infrastructure.stimulation.population.pair_mapping import match_fragment_inputs


def inputs():
    mapping = {'source_id': 10, 'target_id': 20, 'graph_sha256': 'a' * 64,
               'target_morphology_sha256': 'b' * 64,
               'candidates': [{'target_child_node_id': 9, 'target_fraction': .5,
                               'stimulated_ticks_ms': [1, 5]}]}
    events = [{'source_id': 10, 'target_id': 20, 'emission_tick_ms': tick,
               'delivery_tick_ms': tick + 2, 'synapse_count': 1, 'predicted_sign': -1,
               'within_window': tick + 2 <= 6, 'kind': 'physical-source-edge'}
              for tick in (1, 5)]
    return {'source_ids': [10, 20, 30], 'feedback': {'events': events, 'delivery_delay_ms': 2,
                                                    'graph_sha256': 'a' * 64},
            'mappings': [mapping], 'parameters': {-1: {'weight_us': .01, 'tau1_ms': .2,
                'tau2_ms': 2., 'reversal_mv': -80.}}, 'duration_ms': 6, 'max_events': 10}


def test_routes_all_targets_with_explicit_delay_and_outside_window():
    result = population_feedback_schedule(**inputs())
    assert result['event_count'] == 1 and result['outside_window'] == 1
    assert result['events_by_target'][10] == [] and result['events_by_target'][30] == []
    assert result['events_by_target'][20][0]['time_ms'] == 3
    assert result['events_by_target'][20][0]['reversal_mv'] == -80
    assert result['provenance_by_target'][20][0]['source_id'] == 10


def test_partial_feedback_merge_is_independent_of_batch_order():
    value = inputs()
    first = population_feedback_schedule(**value, output_targets=[20])
    second_value = deepcopy(value)
    second_value['mappings'][0]['source_id'] = 30
    for event in second_value['feedback']['events']:
        event['source_id'] = 30
    second = population_feedback_schedule(**second_value, output_targets=[20])
    left = combine_partial_feedback_schedules([10, 20, 30], 'a' * 64, [first, second],
                                              max_events=10)
    right = combine_partial_feedback_schedules([10, 20, 30], 'a' * 64, [second, first],
                                               max_events=10)
    assert left == right
    assert len(left['events_by_target'][20]) == 2
    assert {row['source_id'] for row in left['provenance_by_target'][20]} == {10, 30}


def test_registered_self_edge_routes_back_to_same_physical_cell():
    value = inputs()
    value['mappings'][0]['target_id'] = 10
    for event in value['feedback']['events']:
        event['target_id'] = 10
    result = population_feedback_schedule(**value)
    assert result['events_by_target'][10][0]['time_ms'] == 3
    assert result['provenance_by_target'][10][0]['source_id'] == 10


def test_experimental_gpu_mapping_preserves_schedule_and_rejects_identity_mismatch():
    result = population_feedback_schedule(**inputs())
    gpu_events = feedback_midpoint_events(result, 20, 'b' * 64, [3, 9],
                                          duration_ms=6, nseg_per_edge=1)
    assert gpu_events[0]['segment_index'] == 1
    assert gpu_events[0]['time_ms'] == 3
    assert gpu_events[0]['reversal_mv'] == -80
    with pytest.raises(ValueError, match='mismatch'):
        feedback_midpoint_events(result, 20, 'c' * 64, [3, 9], duration_ms=6, nseg_per_edge=1)
    result['unresolved'].append({'source_id': 10})
    with pytest.raises(ValueError, match='Incomplete'):
        feedback_midpoint_events(result, 20, 'b' * 64, [3, 9], duration_ms=6, nseg_per_edge=1)


def test_experimental_gpu_feedback_maps_to_refined_segment():
    value = inputs()
    value['mappings'][0]['candidates'][0]['target_fraction'] = .9
    result = population_feedback_schedule(**value)
    segments = [(9, 0, 3), (9, 1, 3), (9, 2, 3)]
    mapped = feedback_refined_events(result, 20, 'b' * 64, segments, duration_ms=6)
    assert mapped[0]['segment_index'] == 2
    assert mapped[0]['position'] == .9
    assert mapped[0]['time_ms'] == 3


def test_schedule_preserves_target_observation_for_each_event():
    value = inputs()
    value['source_ids'] = [10, 20, 3]
    row = value['mappings'][0]['candidates'][0]
    row.update(target_position_8nm=[100, 200, 300], target_distance_um=.075)
    result = population_feedback_schedule(**value)
    origin = result['provenance_by_target'][20][0]
    assert origin['target_position_8nm'] == [100, 200, 300]
    assert origin['target_distance_um'] == .075
    row['target_position_8nm'][0] = 1
    assert origin['target_position_8nm'][0] == 100
    encoded = json.dumps({str(key): rows for key, rows in result['provenance_by_target'].items()},
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert result['provenance_sha256'] == hashlib.sha256(encoded).hexdigest()


def test_schedule_rejects_incomplete_target_observation():
    value = inputs()
    value['mappings'][0]['candidates'][0]['target_position_8nm'] = [1, 2, 3]
    with pytest.raises(ValueError, match='target observation provenance'):
        population_feedback_schedule(**value)


def test_refuses_incomplete_geometry_and_unmatched_events():
    value = inputs()
    value['mappings'][0]['unresolved_target_geometry'] = [{}]
    with pytest.raises(ValueError, match='Incomplete'):
        population_feedback_schedule(**value)
    value = inputs()
    value['feedback']['events'][0]['synapse_count'] = 2
    with pytest.raises(ValueError, match='do not match'):
        population_feedback_schedule(**value)
    value = inputs()
    value['parameters'] = {}
    with pytest.raises(ValueError, match='explicit parameters'):
        population_feedback_schedule(**value)
    value = inputs()
    value['feedback']['graph_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='graph identity'):
        population_feedback_schedule(**value)
    value = inputs()
    value['mappings'].append(deepcopy(value['mappings'][0]))
    with pytest.raises(ValueError, match='Duplicate'):
        population_feedback_schedule(**value)


def test_zero_input_produces_empty_schedules_for_every_source():
    value = inputs()
    value['feedback']['events'] = []
    value['mappings'] = []
    value['parameters'] = {}
    result = population_feedback_schedule(**value)
    assert result['event_count'] == 0
    assert result['events_by_target'] == {10: [], 20: [], 30: []}
    assert result['graph_sha256'] == 'a' * 64


def test_event_at_last_sample_is_counted_but_not_applied_to_physical_replay():
    value = inputs()
    value['mappings'][0]['candidates'][0]['stimulated_ticks_ms'] = [4]
    value['feedback']['events'] = [{'source_id': 10, 'target_id': 20, 'emission_tick_ms': 4,
        'delivery_tick_ms': 6, 'synapse_count': 1, 'predicted_sign': -1,
        'within_window': True, 'affects_replay': False, 'kind': 'physical-source-edge'}]
    result = population_feedback_schedule(**value)
    assert result['event_count'] == 0 and result['outside_window'] == 1
    assert result['events_by_target'][20] == []
    value['feedback']['events'][0]['affects_replay'] = True
    with pytest.raises(ValueError, match='feedback event'):
        population_feedback_schedule(**value)


def test_partial_geometry_is_explicit_and_accounts_for_every_event():
    value = inputs()
    value['mappings'][0]['unresolved_target_geometry'] = [{'stimulated_ticks_ms': [1]}]
    value['feedback']['events'][0]['synapse_count'] = 2
    with pytest.raises(ValueError, match='Incomplete'):
        population_feedback_schedule(**value)
    result = population_feedback_schedule(**value, allow_partial_geometry=True)
    assert result['event_count'] == 1 and result['outside_window'] == 1
    assert result['unresolved'][0]['source_id'] == 10
    assert result['unresolved'][0]['target_id'] == 20
    assert result['unresolved'][0]['stimulated_ticks_ms'] == [1]


def test_unresolved_source_is_not_counted_as_a_negative_or_transmitted_event():
    value = inputs()
    value['mappings'][0]['unresolved_source_geometry'] = [{
        'source_position_8nm': [1, 2, 3], 'target_position_8nm': [4, 5, 6],
        'source_distance_um': 2.1}]
    with pytest.raises(ValueError, match='Incomplete'):
        population_feedback_schedule(**value)
    result = population_feedback_schedule(**value, allow_partial_geometry=True)
    assert result['event_count'] == 1
    # Source gaps remain in the source archive; they are not zero events.
    assert result['unresolved'] == []
    value['mappings'][0]['unresolved_source_geometry'][0]['stimulated_ticks_ms'] = []
    with pytest.raises(ValueError, match='source candidates'):
        population_feedback_schedule(**value, allow_partial_geometry=True)


def test_partial_source_mapping_and_feedback_schedule_agree(monkeypatch):
    graph = SimpleNamespace(posts=[0], provenance={'manifest_sha256': 'a' * 64})
    rows = [{'body_pre': 10, 'body_post': 20, 'x_pre': x, 'y_pre': 2, 'z_pre': 3,
             'x_post': x + 5, 'y_post': 5, 'z_post': 6} for x in (1, 2)]
    index = SimpleNamespace(query=lambda *_a, **_k: {
        'pairs': rows, 'truncated': False, 'source_md5': 'verified', 'total': 2, 'returned': 2})
    common = {'included_in_graph': True, 'partner_id': '20', 'control_ticks_ms': []}
    diagnostics = {'body_id': '10', 'source_md5': 'verified', 'graph_sha256': 'a' * 64,
        'simulation_sha256': 'c' * 64, 'threshold_mv': -20., 'duration_ms': 6,
        'source_pairs': 2, 'graph_pairs': 2, 'candidates': [
            {**common, 'source_position_8nm': [1, 2, 3], 'centerline_distance_um': .1,
             'status': 'stimulus_only_crossing', 'stimulated_ticks_ms': [1]},
            {**common, 'source_position_8nm': [2, 2, 3], 'centerline_distance_um': 2.1,
             'status': 'geometry_unresolved', 'stimulated_ticks_ms': None,
             'control_ticks_ms': None}]}
    module = 'service.infrastructure.stimulation.population.pair_mapping.'
    monkeypatch.setattr(module + 'outgoing', lambda *_a: {
        'next_offset': None, 'items': [{'target_id': '20', 'synapse_count': 2}]})
    monkeypatch.setattr(module + 'read_skeleton',
                        lambda *_a: {'swc': 'verified', 'sha256': 'b' * 64, 'body_id': '20'})
    monkeypatch.setattr(module + 'map_fragment_candidates', lambda *_a: {
        'child_node_ids': [9, 10], 'segment_fractions': [.5, .5],
        'centerline_distances_um': [.1, .1]})
    mapping = match_fragment_inputs(diagnostics, index, graph, 20, [],
        max_source_distance_um=2, max_target_distance_um=2, duration_ms=6,
        allow_partial=True, allow_partial_source=True)
    assert len(mapping['candidates']) == len(mapping['unresolved_source_geometry']) == 1
    value = inputs()
    value['mappings'] = [mapping]
    value['feedback']['events'] = value['feedback']['events'][:1]
    result = population_feedback_schedule(**value, allow_partial_geometry=True)
    assert result['event_count'] == 1
    assert result['events_by_target'][20][0]['child_node_id'] == 9
