from types import SimpleNamespace

import numpy as np
import pytest

from service.application.feedback.direct_events import iter_direct_feedback
from service.application.feedback.population_crossings import PopulationCrossings


def test_crossings_collect_across_windows_and_batches():
    collector = PopulationCrossings([1, 2], time_ms=[0., .5, 1., 1.5, 2.],
                                    threshold_mv=-20., duration_ms=2)
    first = {1: [3]}
    collector.accept(0, 2, [{'id': 1, 'selected_voltage_mv': [[-65., -30.]]}], first)
    with pytest.raises(ValueError, match='Incomplete'):
        collector.finish()
    collector.accept(2, 5, [{'id': 1, 'selected_voltage_mv': [[-10., -30., -40.]]}], first)
    collector.accept(0, 5, [{'id': 2, 'selected_voltage_mv': np.empty((0, 5))}], {2: []})
    assert collector.finish() == {1: {3: [1]}, 2: {}}


def test_failed_or_repeated_batch_is_never_complete():
    collector = PopulationCrossings([1], time_ms=[0., .5, 1.],
                                    threshold_mv=-20., duration_ms=1)
    collector.accept(0, 3, [{'id': 1, 'selected_voltage_mv': [[-65., -30., -10.]]}], {1: [0]})
    with pytest.raises(ValueError, match='identities'):
        collector.accept(0, 3, [{'id': 1, 'selected_voltage_mv': [[-65., -30., -10.]]}], {1: [0]})
    with pytest.raises(ValueError, match='Incomplete'):
        collector.finish()


def test_crossings_resolve_synapses_and_route_against_graph():
    collector = PopulationCrossings([10, 20], time_ms=[0., .5, 1., 1.5, 2.],
                                    threshold_mv=-20., duration_ms=2)
    collector.accept(0, 5, [
        {'id': 10, 'selected_voltage_mv': [[-65., -30., -10., -30., -40.]]},
        {'id': 20, 'selected_voltage_mv': np.empty((0, 5))},
    ], {10: [0], 20: []})
    geometries = {10: {'edge_node_ids': np.array([7])},
                  20: {'edge_node_ids': np.array([8])}}
    proof = {10: {'body_id': '10', 'morphology_sha256': 'a'},
             20: {'body_id': '20', 'morphology_sha256': 'b'}}
    diagnostics = {body: {'body_id': str(body), 'morphology_sha256': digest,
        'threshold_mv': -20., 'duration_ms': 2, 'candidates': candidates}
        for body, digest, candidates in [(10, 'a', [{'included_in_graph': True,
            'result_segment_index': 0, 'child_node_id': 7, 'partner_id': '20',
            'source_position_8nm': [1, 2, 3]}]), (20, 'b', [])]}
    outputs = collector.verified_outputs(geometries, proof, diagnostics)
    graph = SimpleNamespace(ids=np.array([10, 20]), ptr=np.array([0, 1, 1]),
        posts=np.array([1]), counts=np.array([1]), signs=np.array([1, -1]))
    events = {body: result['edge_events'] for body, result in outputs.items()}
    routed = list(iter_direct_feedback(graph, [10, 20], [events], duration_ms=2))
    assert routed[0][0]['source_id'] == 10
    assert routed[0][0]['target_id'] == 20
    assert routed[0][0]['emission_tick_ms'] == 1
    assert routed[0][0]['within_window'] is False
    proof[10]['morphology_sha256'] = 'different'
    with pytest.raises(ValueError, match='identity'):
        collector.verified_outputs(geometries, proof, diagnostics)
