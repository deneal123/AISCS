import numpy as np
import pytest

from service.infrastructure.connectome.forced_network import threshold_crossing_ticks
from service.infrastructure.stimulation.experimental_gpu.window_crossings import WindowedCrossings


@pytest.mark.parametrize('cuts', [[0, 5], [0, 1, 3, 5], [0, 2, 4, 5]])
def test_streamed_crossings_match_reference(cuts):
    time = np.array([0., .5, 1., 1.5, 2.])
    values = np.array([-65., -65., -10., -65., -10.])
    stream = WindowedCrossings({10: [3]}, time_ms=time, threshold_mv=-20., duration_ms=2)
    for start, end in zip(cuts[:-1], cuts[1:], strict=True):
        stream.accept(start, end, [{'id': 10, 'selected_voltage_mv': [values[start:end]]}])
    np.testing.assert_array_equal(stream.finish()[10][3],
        threshold_crossing_ticks(time, values, threshold_mv=-20., duration_ms=2))


def test_two_crossings_in_one_tick_keep_the_first_and_count_the_rest():
    # The scheduler reference still rejects the trace because it must produce an
    # unambiguous single-cell event schedule; the streaming reader has to keep
    # going, because a strong stimulus is exactly the case where this happens.
    times, values = [0., .4, .6, 1.], [-65., -10., -65., -10.]
    with pytest.raises(ValueError, match='graph tick'):
        threshold_crossing_ticks(times, values, threshold_mv=-20., duration_ms=1)
    stream = WindowedCrossings({1: [0]}, time_ms=times, threshold_mv=-20., duration_ms=1)
    stream.accept(0, len(times), [{'id': 1, 'selected_voltage_mv': [values]}])
    assert stream.finish() == {1: {0: [1]}}
    assert stream.report() == {'tick_events': 1, 'coincident_crossings': 1,
                               'activity_total': 1}
    assert stream.activity().tolist() == [0, 1, 0, 0]


def test_crossing_that_straddles_a_tick_is_still_rejected():
    # Resolution, unlike coincident crossings, cannot be recovered: the event
    # time is genuinely ambiguous, so the stream keeps rejecting it.
    times, values = [0., .99, 1.01, 2.], [-65., -65., -10., -65.]
    with pytest.raises(ValueError):
        threshold_crossing_ticks(times, values, threshold_mv=-20., duration_ms=2)
    stream = WindowedCrossings({1: [0]}, time_ms=times, threshold_mv=-20., duration_ms=2)
    with pytest.raises(ValueError, match='spans a graph tick'):
        stream.accept(0, len(times), [{'id': 1, 'selected_voltage_mv': [values]}])
    with pytest.raises(ValueError, match='Incomplete'):
        stream.finish()


def _expected_ticks_without_collapsing(voltage, time, threshold_mv):
    """Reference that keeps the first crossing of each tick and drops the rest."""
    indices = np.flatnonzero((voltage[:-1] < threshold_mv) & (voltage[1:] >= threshold_mv)) + 1
    ticks, collapsed = [], 0
    for index in indices:
        tick = int(np.ceil(time[index]))
        if ticks and ticks[-1] == tick:
            collapsed += 1
            continue
        ticks.append(tick)
    return ticks, collapsed


def test_randomized_streamed_crossings_agree_with_reference():
    rng = np.random.default_rng(1729)
    times = np.arange(201) * .05
    for _ in range(100):
        values = np.full(len(times), -65.)
        positions = sorted(rng.choice(np.arange(1, 201), size=5, replace=False))
        values[positions] = 10.
        stream = WindowedCrossings({1: [0]}, time_ms=times, threshold_mv=-20., duration_ms=10)
        for start in range(0, len(times), 17):
            end = min(start + 17, len(times))
            stream.accept(start, end, [{'id': 1,
                'selected_voltage_mv': [values[start:end]]}])
        expected, collapsed = _expected_ticks_without_collapsing(values, times, -20.)
        np.testing.assert_array_equal(stream.finish()[1][0], expected)
        assert stream.report()['coincident_crossings'] == collapsed


def test_many_segments_and_empty_selection_match_reference():
    times = np.arange(41) * .05
    traces = np.full((3, len(times)), -65.)
    traces[0, 10] = 0.
    traces[1, 20] = 0.
    traces[2, 30] = 0.
    stream = WindowedCrossings({7: [3, 5, 9], 8: []}, time_ms=times,
                               threshold_mv=-20., duration_ms=2)
    for start in range(0, len(times), 7):
        end = min(start + 7, len(times))
        stream.accept(start, end, [{'id': 7, 'selected_voltage_mv': traces[:, start:end]},
                                   {'id': 8, 'selected_voltage_mv': np.empty((0, end - start))}])
    result = stream.finish()
    for row, index in enumerate([3, 5, 9]):
        expected = threshold_crossing_ticks(times, traces[row], threshold_mv=-20., duration_ms=2)
        np.testing.assert_array_equal(result[7][index], expected)
    assert result[8] == {}

def test_crossings_inside_one_tick_are_counted_not_rejected():
    # A strong stimulus fires twice inside one millisecond. The graph delivers
    # one event per tick, so the second crossing cannot be transmitted; the
    # stream must keep the first, count the rest and keep going instead of
    # aborting the whole population replay.
    time = np.arange(21) * .05
    values = np.full(len(time), -65.)
    values[2], values[3] = 10., -65.
    values[5], values[6] = 10., -65.
    stream = WindowedCrossings({4: [0]}, time_ms=time, threshold_mv=-20., duration_ms=1)
    stream.accept(0, len(time), [{'id': 4, 'selected_voltage_mv': [values]}])
    ticks = stream.finish()[4][0]
    assert ticks == [1]
    assert stream.report() == {'tick_events': 1, 'coincident_crossings': 1,
                               'activity_total': 1}
    # The counter, not the voltage, is the durable evidence: one spike in graph
    # millisecond 1 and nothing later, even though the trace returned to rest.
    assert stream.activity().tolist() == [0, 1] + [0] * 19


def test_crossings_in_separate_ticks_are_all_kept():
    time = np.arange(41) * .05
    values = np.full(len(time), -65.)
    values[2], values[3] = 10., -65.
    values[22], values[23] = 10., -65.
    stream = WindowedCrossings({4: [0]}, time_ms=time, threshold_mv=-20., duration_ms=2)
    stream.accept(0, len(time), [{'id': 4, 'selected_voltage_mv': [values]}])
    assert stream.finish()[4][0] == [1, 2]
    assert stream.report() == {'tick_events': 2, 'coincident_crossings': 0,
                               'activity_total': 2}
    assert stream.activity().tolist() == [0, 1, 1] + [0] * 38

