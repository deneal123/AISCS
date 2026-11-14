import numpy as np
import pytest

from service.infrastructure.stimulation.experimental_gpu.window_batches import solve_windowed_groups


def test_grouped_windows_preserve_identity_and_original_order(monkeypatch):
    cells = [{'id': body, 'geometry': {'grid': [None] * count}}
             for body, count in [(10, 4), (11, 1), (12, 2)]]
    emitted = []

    def solver(group, stimulus, table, *, window_sink, **kwargs):
        window_sink(0, 2, [{'id': cell['id']} for cell in group])
        return {'time_ms': np.array([0., 1.]),
                'final_voltage_mv': [np.array([cell['id']]) for cell in group],
                'table_clamped_cell_ids': [11] if group[0]['id'] == 11 else []}

    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.window_batches.'
                        'solve_prepared_batch', solver)
    result = solve_windowed_groups(cells, [0., 1.], None, max_cells=2,
        output_budget_bytes=10000, window_steps=1, max_padding_ratio=2,
        allow_table_clamp=True,
        window_sink=lambda indices, start, end, rows: emitted.append(
            (indices, [row['id'] for row in rows])))
    assert emitted == [((1, 2), [11, 12]), ((0,), [10])]
    assert [cell['id'] for cell in result['cells']] == [10, 11, 12]
    assert result['table_clamped_cell_ids'] == [11]


def test_grouped_windows_reject_duplicate_ids():
    cell = {'id': 1, 'geometry': {'grid': [None]}}
    with pytest.raises(ValueError, match='unique'):
        solve_windowed_groups([cell, cell], [0., 1.], None, max_cells=2,
            output_budget_bytes=1000, window_steps=1, max_padding_ratio=2,
            window_sink=lambda *args: None)


@pytest.mark.parametrize('flags,allow', [([999], True), ([1, 1], True), ([1], False)])
def test_grouped_windows_reject_invalid_clamp_receipts(monkeypatch, flags, allow):
    def solver(group, stimulus, table, **kwargs):
        return {'time_ms': np.array([0., 1.]), 'final_voltage_mv': [np.array([0.])],
                'table_clamped_cell_ids': flags}

    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.window_batches.'
                        'solve_prepared_batch', solver)
    with pytest.raises(ValueError, match='boundary receipt'):
        solve_windowed_groups([{'id': 1, 'geometry': {'grid': [None]}}], [0., 1.], None,
            max_cells=1, output_budget_bytes=1000, window_steps=1, max_padding_ratio=2,
            allow_table_clamp=allow, window_sink=lambda *args: None)


def test_cell_major_rejects_incorrect_selection_count_before_solving(monkeypatch):
    cells = [{'id': 1, 'geometry': {'grid': [None, None], 'parents': [-1, 0, 0]}}]
    called = []
    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.window_batches.'
                        'solve_prepared_batch', lambda *a, **k: called.append(True))

    def factory(indices):
        return {'recording_coefficients': {1: [1., 1.]}, 'selected_indices': {1: [0, 1]},
                'sink': lambda *a: None}

    with pytest.raises(ValueError, match='selection count mismatch'):
        solve_windowed_groups(cells, [0., 1.], None, max_cells=1, output_budget_bytes=10000,
            window_steps=1, max_padding_ratio=2, device_window_factory=factory,
            cell_major=True, cell_major_selection_counts=[1])
    assert not called


def test_cell_major_mixed_initial_states_reserve_generic_trace_budget(monkeypatch):
    cells = [{'id': i + 1, 'initial_voltage_mv': -65. if i % 2 else -64.,
              'initial_gates': [.1, .2, .3],
              'geometry': {'grid': [None] * 100, 'parents': [-1] * 100}}
             for i in range(8)]
    groups = []

    def solver(group, stimulus, table, **kwargs):
        groups.append([cell['id'] for cell in group])
        return {'time_ms': np.arange(len(stimulus)),
                'final_voltage_mv': [np.array([0.]) for _ in group],
                'table_clamped_cell_ids': []}

    def factory(indices):
        return {'recording_coefficients': {cells[i]['id']: [1.] * 100 for i in indices},
                'selected_indices': {cells[i]['id']: [0] for i in indices},
                'sink': lambda *a: None}

    monkeypatch.setattr('service.infrastructure.stimulation.experimental_gpu.window_batches.'
                        'solve_prepared_batch', solver)
    solve_windowed_groups(cells, [0.] * 101, None, max_cells=8, output_budget_bytes=100_000,
        window_steps=25, max_padding_ratio=2, device_window_factory=factory,
        cell_major=True, cell_major_selection_counts=[1] * 8)
    assert len(groups) > 1
    assert sorted(body for group in groups for body in group) == list(range(1, 9))
    assert all(16 * 100 * len(group) * 26 + 32 + 26 * len(group) * 2 * 8 <= 100_000
               for group in groups)
