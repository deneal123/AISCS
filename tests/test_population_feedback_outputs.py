import numpy as np
import pytest

from service.application.feedback.outputs import (
    feedback_output_events,
    feedback_output_segment_indices,
    feedback_selected_output_events,
)


def test_uses_each_verified_outgoing_compartment_and_aggregates_by_edge():
    solution = {'time_ms': [0., .5, 1., 1.5, 2.], 'edge_node_ids': np.array([7, 8]),
                'voltage_mv': [[-65, -65, -10, -65, -65], [-65, -65, -65, -65, -65]]}
    proof = {'body_id': '10', 'morphology_sha256': 'a'}
    original = {'body_id': '10', 'morphology_sha256': 'a', 'threshold_mv': -20., 'duration_ms': 2,
                'candidates': [{'included_in_graph': True, 'result_segment_index': 0,
                                'child_node_id': 7, 'partner_id': '20'},
                               {'included_in_graph': True, 'result_segment_index': 0,
                                'child_node_id': 7, 'partner_id': '20'}]}
    events = feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2)
    assert feedback_output_segment_indices(10, solution['edge_node_ids'], proof, original,
                                           threshold_mv=-20., duration_ms=2) == [0]
    assert events == [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 2}]
    with pytest.raises(ValueError, match='source coordinate'):
        feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2,
                               include_candidates=True)
    for index, candidate in enumerate(original['candidates']):
        candidate['source_position_8nm'] = [index, 2, 3]
    details = feedback_output_events(10, solution, proof, original, threshold_mv=-20.,
                                     duration_ms=2, include_candidates=True)
    assert details['edge_events'] == events
    assert details['candidates'][0]['stimulated_ticks_ms'] == [1]
    original['candidates'][0]['centerline_distance_um'] = .1
    original['candidates'][1]['centerline_distance_um'] = 2.1
    partial = feedback_output_events(10, solution, proof, original, threshold_mv=-20.,
        duration_ms=2, include_candidates=True, max_source_distance_um=2.)
    assert partial['edge_events'] == [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
    assert len(partial['candidates']) == 1
    original['candidates'][1]['source_position_8nm'] = [0, 2, 3]
    repeated = feedback_output_events(10, solution, proof, original, threshold_mv=-20.,
                                      duration_ms=2, include_candidates=True)
    assert repeated['edge_events'][0]['count'] == 2
    assert len(repeated['candidates']) == 2
    original['candidates'][1]['result_segment_index'] = 1
    original['candidates'][1]['child_node_id'] = 8
    with pytest.raises(ValueError, match='Conflicting duplicate'):
        feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2,
                               include_candidates=True)
    original['candidates'][1]['result_segment_index'] = 0
    original['candidates'][1]['child_node_id'] = 7
    original['candidates'][0]['child_node_id'] = 8
    with pytest.raises(ValueError, match='compartment'):
        feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2)


def test_remeshed_output_uses_verified_position_instead_of_old_segment_index():
    solution = {'time_ms': [0., .5, 1., 1.5, 2.], 'edge_node_ids': np.array([7, 7, 7, 8]),
                'voltage_mv': [[-65]*5, [-65]*5, [-65, -10, -65, -65, -65], [-65]*5]}
    proof = {'body_id': '10', 'morphology_sha256': 'a',
             'configuration': {'nseg_per_edge': 1, 'nseg_by_edge': {'7': 3}}}
    candidate = {'included_in_graph': True, 'result_segment_index': 0,
                 'child_node_id': 7, 'segment_fraction': .9, 'partner_id': '20'}
    original = {'body_id': '10', 'morphology_sha256': 'a', 'threshold_mv': -20., 'duration_ms': 2,
                'candidates': [candidate]}
    events = feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2)
    assert feedback_output_segment_indices(10, solution['edge_node_ids'], proof, original,
                                           threshold_mv=-20., duration_ms=2) == [2]
    selected = feedback_selected_output_events(10, solution['time_ms'], solution['edge_node_ids'],
        {2: solution['voltage_mv'][2]}, proof, original, threshold_mv=-20., duration_ms=2)
    assert selected == events
    with pytest.raises(ValueError, match='Missing selected'):
        feedback_selected_output_events(10, solution['time_ms'], solution['edge_node_ids'], {},
                                        proof, original, threshold_mv=-20., duration_ms=2)
    assert events == [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
    del candidate['segment_fraction']
    with pytest.raises(ValueError, match='verified output position'):
        feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2)


def test_uniform_refinement_also_remaps_verified_output_positions():
    solution = {'time_ms': [0., .5, 1., 1.5, 2.], 'edge_node_ids': np.array([7, 7, 7]),
                'voltage_mv': [[-65]*5, [-65]*5, [-65, -10, -65, -65, -65]]}
    proof = {'body_id': '10', 'morphology_sha256': 'a', 'configuration': {'nseg_per_edge': 3}}
    original = {'body_id': '10', 'morphology_sha256': 'a', 'threshold_mv': -20., 'duration_ms': 2,
                'candidates': [{'included_in_graph': True, 'result_segment_index': 0,
                                'child_node_id': 7, 'segment_fraction': .9, 'partner_id': '20'}]}
    events = feedback_output_events(10, solution, proof, original, threshold_mv=-20., duration_ms=2)
    assert events == [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
