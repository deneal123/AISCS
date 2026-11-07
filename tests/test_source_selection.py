import numpy as np
import pytest

from service.infrastructure.stimulation.source_selection import earliest_crossing_source


def test_selects_first_transition_with_stable_tie_and_checked_tick():
    time = [0., .25, .5, .75, 1., 1.25, 1.5, 1.75, 2.]
    voltage = np.full((3, len(time)), -65.)
    voltage[1:, 2:4] = 10.
    voltage[0, 5:7] = 10.
    selected = earliest_crossing_source(time, voltage, [10, 11, 12],
                                        threshold_mv=-20., duration_ms=2)
    assert selected['child_node_id'] == 11
    assert selected['segment_index'] == 1
    assert selected['sampling_fraction'] == .5
    assert selected['first_sample_ms'] == .5
    assert selected['event_ticks_ms'] == [1]


def test_returns_none_and_rejects_unknown_or_ambiguous_history():
    time = [0., .5, 1., 1.5, 2.]
    voltage = np.full((2, 5), -65.)
    assert earliest_crossing_source(time, voltage, [10, 11],
                                    threshold_mv=-20., duration_ms=2) is None
    voltage[1, 0] = 0.
    with pytest.raises(ValueError, match='unknown history'):
        earliest_crossing_source(time, voltage, [10, 11], threshold_mv=-20., duration_ms=2)
    voltage[1, 0] = -65.
    voltage[0, 2] = 0.
    with pytest.raises(ValueError, match='spans a graph tick boundary'):
        earliest_crossing_source([0., .75, 1.25, 1.5, 2.], voltage, [10, 11],
                                 threshold_mv=-20., duration_ms=2)


def test_preserves_exact_position_within_discretized_edge():
    time = [0., .5, 1., 1.5, 2.]
    voltage = np.full((6, 5), -65.)
    voltage[5, 1:3] = 0.
    selected = earliest_crossing_source(time, voltage, [10, 10, 10, 11, 11, 11],
                                        threshold_mv=-20., duration_ms=2)
    assert selected['child_node_id'] == 11
    assert selected['sampling_fraction'] == pytest.approx(5 / 6)
    with pytest.raises(ValueError, match='not contiguous'):
        earliest_crossing_source(time, voltage, [10, 11, 10, 11, 11, 10],
                                 threshold_mv=-20., duration_ms=2)


def test_matches_independent_full_matrix_scan_across_chunks():
    rng = np.random.default_rng(3101)
    time = np.arange(101, dtype=float) * .05
    voltage = rng.uniform(-80., -30., size=(600, len(time)))
    voltage[:, 0] = -65.
    voltage[375, 17:19] = 10.
    voltage[2, 24:26] = 10.
    rows, cols = np.nonzero((voltage[:, :-1] < -20.) & (voltage[:, 1:] >= -20.))
    earliest = int(cols.min())
    expected = int(rows[cols == earliest].min())
    selected = earliest_crossing_source(time, voltage, np.arange(1, 601),
                                        threshold_mv=-20., duration_ms=5)
    assert selected['segment_index'] == expected == 375
    assert selected['first_sample_ms'] == time[earliest + 1]


def test_does_not_merge_multiple_transitions_in_one_graph_tick():
    time = np.arange(9, dtype=float) * .25
    voltage = np.full((1, len(time)), -65.)
    voltage[0, [1, 3]] = 10.
    with pytest.raises(ValueError, match='Multiple cell events'):
        earliest_crossing_source(time, voltage, [1], threshold_mv=-20., duration_ms=2)
