from types import SimpleNamespace

import numpy as np
import pytest

from service.infrastructure.connectome.forced_network import (
    contrast_forced_network,
    run_forced_network,
    threshold_crossing_ticks,
)


def graph(sign=1):
    return SimpleNamespace(
        ids=np.array([10, 20, 30]), size=3,
        ptr=np.array([0, 1, 2, 2], dtype=np.int64),
        posts=np.array([1, 2], dtype=np.int32),
        counts=np.array([3000, 3000]), signs=np.array([sign, 1, 1]),
        provenance={"manifest_sha256": "test"},
    )


def test_explicit_source_events_follow_only_edges_and_the_existing_delay():
    outcome = run_forced_network(graph(), seed=1, duration_ms=6,
                                 forced_cell_ids=[10], events={10: [1]})
    np.testing.assert_array_equal(outcome["spike_neurons"], [0, 1, 2])
    np.testing.assert_array_equal(outcome["spike_times_ms"], [1, 3, 5])
    np.testing.assert_array_equal(outcome["counts"], [1, 1, 1])


def test_absent_events_and_inhibitory_source_cannot_create_an_excitatory_wave():
    quiet = run_forced_network(graph(), seed=1, duration_ms=6,
                               forced_cell_ids=[10], events={10: []})
    inhibitory = run_forced_network(graph(-1), seed=1, duration_ms=6,
                                    forced_cell_ids=[10], events={10: [1]})
    assert quiet["counts"].sum() == 0
    np.testing.assert_array_equal(inhibitory["counts"], [1, 0, 0])


def test_scheduled_source_is_not_reexcited_by_graph_feedback():
    cycle = graph()
    cycle.ptr = np.array([0, 1, 2, 3], dtype=np.int64)
    cycle.posts = np.array([1, 2, 0], dtype=np.int32)
    cycle.counts = np.array([3000, 3000, 3000])
    outcome = run_forced_network(cycle, seed=1, duration_ms=10,
                                 forced_cell_ids=[10], events={10: [1]})
    assert outcome["counts"][0] == 1
    assert outcome["counts"][1] >= 1 and outcome["counts"][2] >= 1


def test_sampled_contrast_preserves_dynamics_and_distinguishes_control():
    network = graph()
    arguments = dict(seed=1, duration_ms=6, forced_cell_ids=[10], events={10: [1]})
    plain = run_forced_network(network, **arguments)
    sampled = run_forced_network(network, sample_cell_ids=[30, 20], **arguments)
    np.testing.assert_array_equal(plain['spike_neurons'], sampled['spike_neurons'])
    np.testing.assert_array_equal(plain['spike_times_ms'], sampled['spike_times_ms'])
    np.testing.assert_array_equal(plain['final_voltage_relative_mv'],
                                  sampled['final_voltage_relative_mv'])
    np.testing.assert_array_equal(sampled['sampled_time_ms'], np.arange(7))
    np.testing.assert_array_equal(sampled['sampled_voltage_relative_mv'][-1],
                                  plain['final_voltage_relative_mv'][[2, 1]])
    contrast = contrast_forced_network(network, sample_cell_ids=[30, 20], **arguments)
    np.testing.assert_array_equal(contrast['active_voltage_relative_mv'],
                                  sampled['sampled_voltage_relative_mv'])
    np.testing.assert_array_equal(contrast['voltage_difference_mv'],
        contrast['active_voltage_relative_mv'] - contrast['control_voltage_relative_mv'])
    np.testing.assert_array_equal(contrast['voltage_difference_mv'][0], [0, 0])
    assert np.any(contrast['voltage_difference_mv'][2:] != 0)
    zero = contrast_forced_network(network, seed=1, duration_ms=6, forced_cell_ids=[10],
                                   events={10: []}, sample_cell_ids=[20])
    np.testing.assert_array_equal(zero['voltage_difference_mv'], 0)


@pytest.mark.parametrize('sample', [[], [20, 20], [True], [40], [0]])
def test_reject_invalid_sampled_cells(sample):
    with pytest.raises(ValueError):
        run_forced_network(graph(), seed=1, duration_ms=6, forced_cell_ids=[10],
                           events={10: [1]}, sample_cell_ids=sample)


def test_reject_oversized_sample_before_allocating_recording():
    with pytest.raises(ValueError, match='oversized'):
        run_forced_network(graph(), seed=1, duration_ms=1000, forced_cell_ids=[10],
                           events={10: [1]}, sample_cell_ids=list(range(1, 4001)))


def test_crossing_is_quantized_later_never_earlier():
    ticks = threshold_crossing_ticks([0, .3, .8, 1.4, 2.0], [-2, -1, 1, -1, 2],
                                     threshold_mv=0, duration_ms=2)
    np.testing.assert_array_equal(ticks, [1, 2])


def test_crossing_bounds_preserve_samples_and_validate_tick_identity():
    from service.infrastructure.connectome.forced_network import (
        threshold_crossing_intervals,
        validate_crossing_intervals,
    )
    intervals = threshold_crossing_intervals(
        [0, .3, .8, 1.4, 2.0], [-2, -1, 1, -1, 2], threshold_mv=0, duration_ms=2)
    assert intervals == [{'lower_ms': .3, 'upper_ms': .8, 'tick_ms': 1},
                         {'lower_ms': 1.4, 'upper_ms': 2., 'tick_ms': 2}]
    validate_crossing_intervals(intervals, [1, 2], duration_ms=2)
    with pytest.raises(ValueError, match='graph tick'):
        validate_crossing_intervals([{**intervals[0], 'upper_ms': 1.1}], [1], duration_ms=2)
    tiny = threshold_crossing_intervals([0, 1e-12, 1], [-1, 1, -1],
                                        threshold_mv=0, duration_ms=1)
    validate_crossing_intervals(tiny, [1], duration_ms=1)


def test_clock_roundoff_is_tolerated_without_snapping_a_later_event():
    ticks = threshold_crossing_ticks([0, 1e-12, 1, 2 + 1e-12, 3, 3 + 2e-9, 4 - 1e-12],
                                     [-1, 1, -1, 1, -1, 1, -1],
                                     threshold_mv=0, duration_ms=4)
    np.testing.assert_array_equal(ticks, [1, 2, 4])


def test_crossing_that_straddles_a_graph_tick_is_not_assigned_arbitrarily():
    with pytest.raises(ValueError, match='spans a graph tick'):
        threshold_crossing_ticks([0, .99, 1.01, 2], [-65, -30, -10, -65],
                                 threshold_mv=-20, duration_ms=2)
    ticks = threshold_crossing_ticks([0, 1, 1.01, 2], [-65, -30, -10, -65],
                                     threshold_mv=-20, duration_ms=2)
    np.testing.assert_array_equal(ticks, [2])


@pytest.mark.parametrize('time,voltage', [([0, .2, .5, 1], [-1, 1, -1, 1]),
                                          ([0, 1], [1, -1]), ([0, 0], [-1, 1])])
def test_ambiguous_or_invalid_traces_are_rejected(time, voltage):
    with pytest.raises(ValueError):
        threshold_crossing_ticks(time, voltage, threshold_mv=0, duration_ms=1)


@pytest.mark.parametrize('ids,events', [([10], {}), ([10, 10], {10: []}),
                                        ([10], {10: [1, 1]}), ([10], {10: [True]}),
                                        ([40], {40: []})])
def test_reject_invalid_schedules(ids, events):
    with pytest.raises(ValueError):
        run_forced_network(graph(), seed=1, duration_ms=6, forced_cell_ids=ids, events=events)
