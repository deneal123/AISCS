import numpy as np
import pytest

from service.application.feedback.population_windowed import PopulationWindowedFeedback
from tests.test_windowed_feedback_outputs import collector


def test_streamed_feedback_preserves_crossing_across_window_boundary():
    source = collector()
    cell = {'id': 10, 'geometry': source.geometries[10], 'morphology_sha256': 'a'}
    staged = []
    target = PopulationWindowedFeedback([10], metadata_factory=lambda cells: {
        'provenance': source.provenance, 'diagnostics': source.diagnostics},
        event_sink=staged.append, time_ms=[0., .5, 1., 1.5, 2.], threshold_mv=-20.,
        duration_ms=2, electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
        conductivity_s_m=.3, clearance_um=1.)
    device = target.factory([cell])
    assert device['selected_indices'] == {10: [0]}
    device['sink'](0, 2, [{'id': 10, 'neural_uv': [1., 2.],
                            'selected_voltage_mv': [[-65., -65.]]}])
    assert not staged
    device['sink'](2, 5, [{'id': 10, 'neural_uv': [3., 4., 5.],
                            'selected_voltage_mv': [[-10., -65., -65.]]}])
    assert staged[0][10]['edge_events'] == [
        {'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
    np.testing.assert_array_equal(target.finish(), [1., 2., 3., 4., 5.])
    from service.infrastructure.connectome.edge_forced_network import run_edge_forced_network
    from tests.test_forced_network import graph

    options = dict(seed=1, duration_ms=6, forced_cell_ids=[10], sample_cell_ids=[20])
    actual = run_edge_forced_network(graph(), edge_events=staged[0][10]['edge_events'], **options)
    quiet = run_edge_forced_network(graph(), edge_events=[], **options)
    assert np.any(actual['sampled_voltage_relative_mv'] != quiet['sampled_voltage_relative_mv'])


def test_streamed_feedback_rejects_wrong_morphology():
    source = collector()
    target = PopulationWindowedFeedback([10], metadata_factory=lambda cells: {
        'provenance': source.provenance, 'diagnostics': source.diagnostics},
        event_sink=lambda data: None, time_ms=[0., 1., 2.], threshold_mv=-20.,
        duration_ms=2, electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
        conductivity_s_m=.3, clearance_um=1.)
    with pytest.raises(ValueError, match='morphology identity'):
        target.factory([{'id': 10, 'geometry': source.geometries[10],
                         'morphology_sha256': 'wrong'}])


def test_unresolved_source_is_archived_without_claiming_a_negative_observation():
    from service.application.feedback.outputs import merge_archived_source_events

    source = collector()
    diagnostic = source.diagnostics[10]
    diagnostic['candidates'][0]['centerline_distance_um'] = .1
    diagnostic['candidates'][0]['status'] = 'no_crossing'
    diagnostic['candidates'].append({'included_in_graph': True, 'partner_id': '20',
        'source_position_8nm': [4, 5, 6], 'centerline_distance_um': 2.5,
        'status': 'geometry_unresolved', 'stimulated_ticks_ms': None, 'control_ticks_ms': None})
    cell = {'id': 10, 'geometry': source.geometries[10], 'morphology_sha256': 'a'}
    staged = []
    target = PopulationWindowedFeedback([10], metadata_factory=lambda cells: {
        'provenance': source.provenance, 'diagnostics': source.diagnostics},
        event_sink=staged.append, time_ms=[0., .5, 1., 1.5, 2.], threshold_mv=-20.,
        duration_ms=2, electrode_um=[10., 0., 0.], reference_um=[20., 0., 0.],
        conductivity_s_m=.3, clearance_um=1., max_source_distance_um=2.)
    device = target.factory([cell])
    assert device['selected_indices'] == {10: [0]}
    device['sink'](0, 5, [{'id': 10, 'neural_uv': [0.] * 5,
                            'selected_voltage_mv': [[-65., -65., -10., -65., -65.]]}])
    archived = staged[0][10]
    assert len(archived['candidates']) == 2
    assert archived['edge_events'] == [{'source_id': 10, 'target_id': 20, 'tick': 1, 'count': 1}]
    merged = merge_archived_source_events(diagnostic, archived, control=archived)
    assert merged['candidates'][1]['status'] == 'geometry_unresolved'
    assert merged['candidates'][1]['stimulated_ticks_ms'] is None
    assert merged['candidates'][1]['control_ticks_ms'] is None
    target.finish()


def test_inconsistent_unresolved_source_is_not_archived_as_observed():
    from service.application.feedback.outputs import feedback_selected_output_ticks

    source = collector()
    diagnostic = source.diagnostics[10]
    diagnostic['candidates'][0].update(centerline_distance_um=2.5, status='no_crossing')
    with pytest.raises(ValueError, match='Invalid unresolved source candidate'):
        feedback_selected_output_ticks(10, source.geometries[10]['edge_node_ids'], {},
            source.provenance[10], diagnostic, threshold_mv=-20., duration_ms=2,
            include_candidates=True, include_unresolved_candidates=True, max_source_distance_um=2.)
    diagnostic['candidates'][0]['status'] = 'geometry_unresolved'
    with pytest.raises(ValueError, match='matching distance cutoff'):
        feedback_selected_output_ticks(10, source.geometries[10]['edge_node_ids'], {0: []},
            source.provenance[10], diagnostic, threshold_mv=-20., duration_ms=2,
            include_candidates=True, include_unresolved_candidates=True)
