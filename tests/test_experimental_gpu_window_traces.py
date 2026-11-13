import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.window_traces import WindowedTraceSelector


def test_selector_preserves_order_and_cross_window_values():
    selector = WindowedTraceSelector({10: 3, 20: 2}, {10: [2, 0], 20: [1]}, samples=4)
    data = {10: np.arange(12.).reshape(3, 4), 20: np.arange(8.).reshape(2, 4)}
    with pytest.raises(ValueError, match='Incomplete'):
        selector.finish()
    for start, end in [(0, 1), (1, 3), (3, 4)]:
        selector.accept(start, end, [{'id': body, 'voltage_mv': values[:, start:end]}
                                     for body, values in data.items()])
    result = selector.finish()
    np.testing.assert_array_equal(result[10], data[10][[2, 0]])
    np.testing.assert_array_equal(result[20], data[20][[1]])


def test_selector_rejects_malformed_window_atomically():
    selector = WindowedTraceSelector({1: 2, 2: 1}, {1: [0], 2: [0]}, samples=2)
    with pytest.raises(ValueError, match='Non-finite'):
        selector.accept(0, 1, [{'id': 1, 'voltage_mv': [[1.], [2.]]},
                               {'id': 2, 'voltage_mv': [[float('nan')]]}])
    assert selector.next_sample == 0


@pytest.mark.parametrize('indices', [[0, 0], [-1], [2], [True]])
def test_selector_rejects_invalid_indexes(indices):
    with pytest.raises(ValueError, match='indexes'):
        WindowedTraceSelector({1: 2}, {1: indices}, samples=2)
