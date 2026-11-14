import math
import random

import pytest

from service.infrastructure.stimulation.experimental_gpu.batching import (
    estimate_output_bytes,
    plan_batches,
    plan_cell_major_window_batches,
    plan_output_batches,
    plan_window_batches,
)


def test_output_batch_planner_matches_exhaustive_grouping():
    rng = random.Random(35)
    for _ in range(100):
        counts = [rng.randint(1, 200) for _ in range(rng.randint(1, 70))]
        samples = rng.randint(1, 20)
        budget = estimate_output_bytes(max_segments=max(counts), batch_size=2,
                                       samples=samples, state_trace_cells=0)['total']
        def size(group, counts=counts, samples=samples):
            return estimate_output_bytes(max_segments=max(counts[i] for i in group),
                batch_size=len(group), samples=samples, state_trace_cells=0)['total']
        if size(list(range(len(counts)))) <= budget:
            expected = [list(range(len(counts)))]
        else:
            expected, current = [], []
            for index in sorted(range(len(counts)), key=lambda i: (counts[i], i)):
                if current and size([*current, index]) > budget:
                    expected.append(current)
                    current = []
                current.append(index)
            if current:
                expected.append(current)
        assert plan_output_batches(counts, samples=samples, output_budget_bytes=budget) == expected


def test_cell_major_window_planner_bounds_real_reduced_state():
    nodes = [200, 100, 150, 250]
    segments = [100, 50, 75, 120]
    selections = [1, 0, 3, 2]
    budget = 40000
    groups = plan_cell_major_window_batches(nodes, segments, selections, max_cells=4,
        samples=101, window_steps=5, output_budget_bytes=budget, max_padding_ratio=2)
    assert sorted(index for group in groups for index in group) == list(range(4))
    for group in groups:
        n = max(nodes[i] for i in group)
        s = max(segments[i] for i in group)
        k = max(1, *(selections[i] for i in group))
        required = len(group) * (40 * n + 24 * s + 8 * k + 16 + 6 * (k + 1) * 8)
        assert required <= budget
        assert s * len(group) <= 2 * sum(segments[i] for i in group)


def test_cell_major_planner_can_group_more_than_full_trace_planner():
    kwargs = dict(max_cells=10, samples=101, window_steps=25,
                  output_budget_bytes=120000, max_padding_ratio=2)
    reduced = plan_cell_major_window_batches([200] * 4, [100] * 4, [1] * 4, **kwargs)
    full = plan_window_batches([100] * 4, **kwargs)
    assert reduced == [[0, 1, 2, 3]]
    assert len(full) > 1


def test_cell_major_planner_rejects_oversize_or_invalid_selection():
    kwargs = dict(max_cells=2, samples=3, window_steps=1,
                  output_budget_bytes=100, max_padding_ratio=2)
    with pytest.raises(ValueError, match='exceeds'):
        plan_cell_major_window_batches([10], [5], [1], **kwargs)
    with pytest.raises(ValueError, match='limits'):
        plan_cell_major_window_batches([10], [5], [6], **kwargs)


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
def test_cell_major_planner_reserves_generic_fallback_buffers():
    from service.infrastructure.stimulation.experimental_gpu.batching import (
        plan_cell_major_window_batches,
    )

    options = dict(max_cells=8, samples=101, window_steps=25,
                   output_budget_bytes=100_000, max_padding_ratio=2)
    reduced = plan_cell_major_window_batches([100] * 8, [100] * 8, [1] * 8, **options)
    fallback = plan_cell_major_window_batches([100] * 8, [100] * 8, [1] * 8,
                                              generic_fallback=True, **options)
    assert len(fallback) > len(reduced)
    for group in fallback:
        assert 16 * 100 * len(group) * 26 + 32 + 26 * len(group) * 2 * 8 <= 100_000
