import numpy as np
import pytest

from service.infrastructure.stimulation.threshold_diagnostics import (
    compartment_crossing_events,
    compartment_crossing_summary,
)


def test_full_cell_diagnostic_distinguishes_missed_and_earlier_crossings():
    time = np.arange(5, dtype=float)
    voltage = np.full((260, 5), -65.)
    voltage[0, 1:3] = -10.
    voltage[257, 2:4] = -10.
    voltage[259] = 0.
    summary = compartment_crossing_summary(time, voltage, selected_index=257, threshold_mv=-20.)
    assert summary == {"compartments": 260, "initial_at_or_above_threshold": 1,
                       "compartments_with_upward_crossing": 2,
                       "earliest_crossing_sample_ms": 1., "selected_crossings": 1,
                       "selected_first_crossing_sample_ms": 2.}


def test_missing_selected_event_does_not_discard_other_compartment_crossings():
    time = np.arange(3, dtype=float)
    voltage = np.array([[-65., -65., -65.], [-65., -10., -65.]])
    summary = compartment_crossing_summary(time, voltage, selected_index=0, threshold_mv=-20.)
    assert summary["selected_crossings"] == 0
    assert summary["compartments_with_upward_crossing"] == 1
    assert summary["earliest_crossing_sample_ms"] == 1.


def test_dense_crossings_remain_correct_across_chunks():
    time = np.arange(2001, dtype=float)
    voltage = np.tile(np.where(np.arange(2001) % 2 == 0, -65., -10.), (260, 1))
    summary = compartment_crossing_summary(time, voltage, selected_index=259, threshold_mv=-20.)
    assert summary["compartments_with_upward_crossing"] == 260
    assert summary["selected_crossings"] == 1000
    assert summary["earliest_crossing_sample_ms"] == 1.


def test_summary_matches_independent_randomized_reference():
    rng = np.random.default_rng(4501)
    for count in (1, 17, 256, 257):
        time = np.arange(15, dtype=float) / 10
        voltage = rng.normal(-20, 5, (count, len(time)))
        selected = count - 1
        summary = compartment_crossing_summary(time, voltage, selected_index=selected,
                                                 threshold_mv=-20.)
        events = [(i, j) for i, row in enumerate(voltage)
                  for j in range(1, len(time)) if row[j - 1] < -20 <= row[j]]
        selected_events = [j for i, j in events if i == selected]
        assert summary["compartments_with_upward_crossing"] == len({i for i, _ in events})
        assert summary["selected_crossings"] == len(selected_events)
        assert summary["earliest_crossing_sample_ms"] == (
            float(time[min(j for _, j in events)]) if events else None
        )
        assert summary["selected_first_crossing_sample_ms"] == (
            float(time[min(selected_events)]) if selected_events else None
        )


def test_spatial_events_keep_solver_indices_and_sample_times():
    time = np.array([0., .5, 1., 1.5])
    voltage = np.array([[-65., -10., -65., -10.], [-65., -65., -10., -65.]])
    positions = np.array([[1., 2., 3.], [4., 5., 6.]])
    result = compartment_crossing_events(time, voltage, positions, threshold_mv=-20.)
    np.testing.assert_array_equal(result['compartment_indices'], [0, 0, 1])
    np.testing.assert_array_equal(result['sample_indices'], [1, 3, 2])
    np.testing.assert_array_equal(time[result['sample_indices']], [.5, 1.5, 1.])
    np.testing.assert_array_equal(result['midpoints_um'], positions)
    positions[0, 0] = 999
    assert result['midpoints_um'][0, 0] == 1.


def test_spatial_events_fail_closed_when_budget_exceeded():
    voltage = np.tile(np.array([-65., -10., -65., -10.]), (3, 1))
    with pytest.raises(ValueError, match='event limit'):
        compartment_crossing_events([0., 1., 2., 3.], voltage, np.zeros((3, 3)),
                                    threshold_mv=-20., max_events=5)


@pytest.mark.parametrize("index,threshold", [(True, -20.), (2, -20.), (0, True), (0, np.nan)])
def test_invalid_inputs_rejected(index, threshold):
    with pytest.raises(ValueError, match="Invalid"):
        compartment_crossing_summary([0., 1.], [[-65., -10.]],
                                     selected_index=index, threshold_mv=threshold)
