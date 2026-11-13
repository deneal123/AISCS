import math

import pytest

from service.infrastructure.stimulation.experimental_gpu.batching import (
    estimate_output_bytes,
    plan_batches,
    plan_output_batches,
    plan_window_batches,
)


def test_output_estimate_includes_current_and_bounded_state_traces():
    result = estimate_output_bytes(max_segments=10, batch_size=6, samples=20)
    assert result == {'currents': 9600, 'voltages': 9600, 'state_trace': 19200, 'total': 38400}
    assert estimate_output_bytes(max_segments=10, batch_size=1, samples=20)['total'] == 9600
    assert estimate_output_bytes(max_segments=10, batch_size=1, samples=20,
                                 state_trace_cells=0)['total'] == 3232


@pytest.mark.parametrize('segments,batch,samples', [(0, 1, 1), (1, True, 1), (1, 1, -1)])
def test_output_estimate_rejects_invalid_dimensions(segments, batch, samples):
    with pytest.raises(ValueError):
        estimate_output_bytes(max_segments=segments, batch_size=batch, samples=samples)


def test_groups_by_size_without_losing_original_indices():
    counts = [6190, 434, 1075, 416, 441, 907, 560, 458]
    batches = plan_batches(counts, max_cells=8, max_padded_segments=10000, max_padding_ratio=1.6)
    assert sorted(index for batch in batches for index in batch) == list(range(len(counts)))
    assert batches[-1] == [0]
    for batch in batches:
        padded = max(counts[i] for i in batch) * len(batch)
        assert padded <= 10000
        assert padded <= 1.6 * sum(counts[i] for i in batch)
    grouped_slots = sum(max(counts[i] for i in batch) * len(batch) for batch in batches)
    assert grouped_slots < max(counts) * len(counts)


@pytest.mark.parametrize('counts,limits', [
    ([1, True], {}), ([0], {}), ([2.0], {}), ([11], {'max_padded_segments': 10}),
    ([1], {'max_cells': 0}), ([1], {'max_padding_ratio': math.nan}),
    ([1], {'max_padding_ratio': math.inf}), ([1], {'max_padding_ratio': .9}),
])
def test_invalid_or_oversized_inputs_fail_closed(counts, limits):
    kwargs = {'max_cells': 8, 'max_padded_segments': 100, 'max_padding_ratio': 2}
    kwargs.update(limits)
    with pytest.raises(ValueError):
        plan_batches(counts, **kwargs)


def test_empty_and_equal_sizes_are_deterministic():
    kwargs = {'max_cells': 2, 'max_padded_segments': 4, 'max_padding_ratio': 1}
    assert plan_batches([], **kwargs) == []
    assert plan_batches([2, 2, 2], **kwargs) == [[0, 1], [2]]


def test_output_batches_respect_exact_buffer_budget_and_preserve_identity():
    counts = [100, 4, 3, 2]
    budget = estimate_output_bytes(max_segments=100, batch_size=1, samples=20,
                                   state_trace_cells=0)['total']
    batches = plan_output_batches(counts, samples=20, output_budget_bytes=budget)
    assert sorted(i for batch in batches for i in batch) == list(range(len(counts)))
    assert len(batches) > 1
    for batch in batches:
        assert estimate_output_bytes(max_segments=max(counts[i] for i in batch),
                                     batch_size=len(batch), samples=20,
                                     state_trace_cells=0)['total'] <= budget
    with pytest.raises(ValueError, match='morphology'):
        plan_output_batches([100], samples=20, output_budget_bytes=budget - 1)


def test_window_batches_enforce_exact_output_budget_and_restore_indices():
    counts = [100, 2, 3, 10, 10]
    budget = estimate_output_bytes(max_segments=100, batch_size=1, samples=6,
                                   state_trace_cells=0)['total']
    batches = plan_window_batches(counts, max_cells=2, samples=201, window_steps=5,
                                  output_budget_bytes=budget, max_padding_ratio=2)
    assert sorted(index for batch in batches for index in batch) == list(range(len(counts)))
    for batch in batches:
        assert len(batch) <= 2
        assert estimate_output_bytes(max_segments=max(counts[i] for i in batch),
                                     batch_size=len(batch), samples=6,
                                     state_trace_cells=0)['total'] <= budget
    with pytest.raises(ValueError, match='budget'):
        plan_window_batches([100], max_cells=2, samples=201, window_steps=5,
                            output_budget_bytes=budget - 1, max_padding_ratio=2)
