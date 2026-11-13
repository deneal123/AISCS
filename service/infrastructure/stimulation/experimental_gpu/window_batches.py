"""Execute explicitly prepared independent cells in bounded output windows."""

from .batch_solver import solve_prepared_batch
from .batching import plan_window_batches


def solve_windowed_groups(cells, stimulus_midpoint, rate_table, *, max_cells,
                          output_budget_bytes, window_steps, max_padding_ratio,
                          window_sink=None, dt_ms=.025, allow_table_clamp=False,
                          check_cancelled=None, progress=None, packing_cache=None,
                          device_window_factory=None, timing_sink=None,
                          cell_major=False, cell_major_block_threads=512,
                          block_cell_segments=40000):
    """Emit windows per size-sorted group and return metadata in input order.

    ``window_sink`` receives (original indices, start, end, rows). Results may
    arrive out of input order; consumers must use the supplied indices. The
    output budget does not bound prepared geometry or total RAM/VRAM. This is
    independent-cell replay, not network feedback or physiological validation.
    """
    if (not isinstance(cells, list) or not cells
            or ((window_sink is None) == (device_window_factory is None))
            or (window_sink is not None and not callable(window_sink))
            or (device_window_factory is not None and not callable(device_window_factory))
            or (timing_sink is not None and not callable(timing_sink))
            or (check_cancelled is not None and not callable(check_cancelled))
            or (progress is not None and not callable(progress))
            or type(cell_major) is not bool
            or (cell_major and device_window_factory is None)
            or any(not isinstance(cell, dict) or not isinstance(cell.get('geometry'), dict)
                   or not isinstance(cell['geometry'].get('grid'), list) for cell in cells)):
        raise ValueError('Invalid window group request')
    ids = [cell.get('id') for cell in cells]
    if any(type(body) is not int or body <= 0 for body in ids) or len(set(ids)) != len(ids):
        raise ValueError('Cell IDs must be unique positive integers')
    counts = [len(cell['geometry']['grid']) for cell in cells]
    groups = plan_window_batches(counts, max_cells=max_cells, samples=len(stimulus_midpoint),
                                 window_steps=window_steps, output_budget_bytes=output_budget_bytes,
                                 max_padding_ratio=max_padding_ratio)
    outputs = [None] * len(cells)
    clamped = set()
    time_ms = None
    for group_number, indices in enumerate(groups):
        if check_cancelled is not None:
            check_cancelled()
        group = [cells[index] for index in indices]

        def accept(start, end, rows, *, expected=tuple(cell['id'] for cell in group),
                   original_indices=tuple(indices)):
            if tuple(row.get('id') for row in rows) != expected:
                raise ValueError('GPU window identity mismatch')
            window_sink(original_indices, start, end, rows)

        if device_window_factory is None:
            sink_options = {'window_sink': accept}
        else:
            device = device_window_factory(tuple(indices))
            if (not isinstance(device, dict) or set(device) !=
                    {'recording_coefficients', 'selected_indices', 'sink'}
                    or not callable(device['sink'])):
                raise ValueError('Invalid GPU device window configuration')
            def accept_device(start, end, rows, *, expected=tuple(cell['id'] for cell in group),
                              sink=device['sink']):
                if tuple(row.get('id') for row in rows) != expected:
                    raise ValueError('GPU window identity mismatch')
                sink(start, end, rows)

            sink_options = {'device_window_sink': accept_device,
                            'recording_coefficients': device['recording_coefficients'],
                            'selected_indices': device['selected_indices']}
        fast_options = ({'cell_major': True, 'cell_major_block_threads': cell_major_block_threads,
                         'block_cell_segments': block_cell_segments} if cell_major else {})
        result = solve_prepared_batch(group, stimulus_midpoint, rate_table, dt_ms=dt_ms,
            output_budget_bytes=output_budget_bytes, window_steps=window_steps,
            allow_table_clamp=allow_table_clamp, check_cancelled=check_cancelled,
            packing_cache=packing_cache, timing_sink=timing_sink, **sink_options, **fast_options)
        if len(result['final_voltage_mv']) != len(indices):
            raise ValueError('Incomplete GPU window group')
        flags = result.get('table_clamped_cell_ids')
        if (not isinstance(flags, list) or any(type(body) is not int for body in flags)
                or len(flags) != len(set(flags))
                or not set(flags).issubset({cell['id'] for cell in group})
                or (flags and not allow_table_clamp)):
            raise ValueError('Invalid GPU table boundary receipt')
        if time_ms is None:
            time_ms = result['time_ms']
        else:
            import numpy as np

            if not np.array_equal(time_ms, result['time_ms']):
                raise ValueError('Inconsistent GPU window time grid')
        for index, final in zip(indices, result['final_voltage_mv'], strict=True):
            outputs[index] = {'id': ids[index], 'final_voltage_mv': final}
        clamped.update(flags)
        if progress is not None:
            progress(group_number + 1, len(groups))
    return {'time_ms': time_ms, 'cells': outputs,
            'table_clamped_cell_ids': [body for body in ids if body in clamped]}
