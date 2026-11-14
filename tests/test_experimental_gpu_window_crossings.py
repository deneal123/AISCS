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


@pytest.mark.parametrize('times,values', [([0., .4, .6, 1.], [-65., -10., -65., -10.]),
                                         ([0., .99, 1.01, 2.], [-65., -65., -10., -65.])])
def test_streamed_crossings_reject_same_ambiguities(times, values):
    with pytest.raises(ValueError):
        threshold_crossing_ticks(times, values, threshold_mv=-20., duration_ms=int(times[-1]))
    stream = WindowedCrossings({1: [0]}, time_ms=times, threshold_mv=-20.,
                               duration_ms=int(times[-1]))
    with pytest.raises(ValueError):
        stream.accept(0, len(times), [{'id': 1, 'selected_voltage_mv': [values]}])
    with pytest.raises(ValueError, match='Incomplete'):
        stream.finish()


def test_randomized_streamed_crossings_agree_with_reference():
    rng = np.random.default_rng(1729)
    times = np.arange(201) * .05
    for _ in range(100):
        values = np.full(len(times), -65.)
        positions = sorted(rng.choice(np.arange(1, 201), size=5, replace=False))
        values[positions] = 10.
        stream = WindowedCrossings({1: [0]}, time_ms=times, threshold_mv=-20., duration_ms=10)
        try:
            expected = threshold_crossing_ticks(times, values, threshold_mv=-20., duration_ms=10)
        except ValueError:
            with pytest.raises(ValueError):
                for start in range(0, len(times), 17):
                    end = min(start + 17, len(times))
                    stream.accept(start, end, [{'id': 1,
                        'selected_voltage_mv': [values[start:end]]}])
        else:
            for start in range(0, len(times), 17):
                end = min(start + 17, len(times))
                stream.accept(start, end, [{'id': 1,
                    'selected_voltage_mv': [values[start:end]]}])
            np.testing.assert_array_equal(stream.finish()[1][0], expected)


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
