import pytest

from service.application.feedback.convergence import compare_edge_events, compare_recordings


def test_recording_comparison_uses_only_matching_times_without_interpolation():
    result = compare_recordings([0, .5, 1 + 1e-11], [0, 1, -1],
                                [0, .25, .5, .75, 1], [0, 5, .5, 5, -1])
    assert result['max_abs_difference_uv'] == pytest.approx(.5)
    assert result['rms_difference_uv'] == pytest.approx((.25 / 3) ** .5)
    assert result['max_difference_over_reference_peak'] == pytest.approx(.5)
    zero = compare_recordings([0, 1], [0, 0], [0, 1], [0, 0])
    assert zero['max_difference_over_reference_peak'] is None


def test_recording_comparison_rejects_unmatched_grid_and_nonfinite_values():
    with pytest.raises(ValueError, match='does not contain'):
        compare_recordings([0, .4, 1], [0, 0, 0], [0, .5, .75, 1], [0, 0, 0, 0])
    with pytest.raises(ValueError, match='Incompatible'):
        compare_recordings([0, 1], [0, float('nan')], [0, 1], [0, 0])
    with pytest.raises(ValueError, match='not finite'):
        compare_recordings([0, 1], [0, 1e308], [0, 1], [0, -1e308])


def test_graph_event_comparison_counts_changes_and_rejects_duplicates():
    event = {'source_id': 1, 'target_id': 2, 'tick': 3, 'count': 2}
    reference = [{'source_id': 1, 'target_id': 2, 'tick': 3, 'count': 1},
                 {'source_id': 1, 'target_id': 4, 'tick': 5, 'count': 3}]
    result = compare_edge_events([event], reference)
    assert result['changed_source_partner_ticks'] == 2
    assert result['absolute_count_difference'] == 4
    with pytest.raises(ValueError, match='Duplicate'):
        compare_edge_events([event, event], reference)
