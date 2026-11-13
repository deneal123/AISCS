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
