"""Experimental single-cell CUDA execution from already verified geometry."""

import numpy as np

from .events import refined_segment_events
from .execution import execute_windows
from .packing import pack_trees


def solve_single_cell(geometry, field_current_na, events, stimulus_midpoint, rate_table,
                      initial_gates, *, initial_voltage_mv=-65.0, window_steps=25,
                      progress=None, check_cancelled=None):
    """Solve one prepared morphology at 0.025 ms; return arrays in host memory.

    The caller must validate provenance, contacts, geometry and any relocation
    of endpoint events. The supplied field is current per segment at unit pulse
    amplitude, not the electrode voltage. This does not run a network, publish
    an experiment or establish a physiological model.
    """
    packed = pack_trees([(geometry['parents'], geometry['conductances'],
                          geometry['segment_nodes'])])
    count = int(packed.lengths[0])
    field = np.asarray(field_current_na, dtype=np.float64)
    area = np.asarray(geometry['area'], dtype=np.float64)
    stimulus = np.asarray(stimulus_midpoint, dtype=np.float64)
    table = np.asarray(rate_table, dtype=np.float64)
    gates_initial = np.asarray(initial_gates, dtype=np.float64)
    if (not isinstance(geometry.get('grid'), list) or len(geometry['grid']) != count
            or field.shape != (count,) or area.shape != (count,) or np.any(area <= 0)
            or stimulus.ndim != 1 or len(stimulus) < 2 or stimulus[0] != 0
            or table.shape != (201, 6) or np.any(table[:, 1::2] <= 0)
            or gates_initial.shape != (3,) or np.any(gates_initial < 0)
            or np.any(gates_initial > 1) or isinstance(initial_voltage_mv, bool)
            or not isinstance(initial_voltage_mv, int | float)
            or not np.isfinite(initial_voltage_mv)
            or not -100 <= initial_voltage_mv <= 100
            or any(not np.isfinite(value).all() for value in
                   (field, area, stimulus, table, gates_initial))):
        raise ValueError('Invalid prepared GPU model inputs')
    steps = len(stimulus)
    mapped = refined_segment_events(events, geometry['grid'], duration_ms=(steps - 1) * .025)
    event_count = len(mapped)

    from numba import cuda

    from .hines_kernel import batched, static_diagonal

    def column(key, dtype=np.float64):
        # Keep two dimensions, even when the event schedule is empty.
        return np.asarray([event[key] for event in mapped], dtype=dtype).reshape(-1, 1)

    initial = np.zeros((count, 1, 4), dtype=np.float64)
    initial[:, 0, 0] = initial_voltage_mv
    initial[:, 0, 1:] = gates_initial
    arrays = [table, np.zeros(steps), stimulus, packed.parents, packed.conductances,
              packed.segment_nodes, area[:, None], field[:, None], initial,
              column('time_ms'), column('weight_us'), column('segment_index', np.int64),
              column('reversal_mv'), column('tau1_ms'), column('tau2_ms'),
              np.asarray([event_count], dtype=np.int64), packed.lengths, packed.nodes,
              packed.node_segments, packed.level_bounds, packed.group_parents,
              packed.group_offsets, packed.group_children, packed.child_offsets,
              packed.child_indices, packed.level_counts]
    buffers = [cuda.to_device(value) for value in arrays]
    node_count = int(packed.nodes[0])
    fixed_diagonal = cuda.device_array((node_count, 1))
    static_diagonal[1, 64](buffers[4], buffers[17], buffers[-3], buffers[-2], fixed_diagonal)
    diagonal = cuda.device_array((node_count, 1))
    rhs = cuda.device_array((node_count, 1))
    voltage = cuda.device_array((node_count, 1))
    inverses = cuda.device_array((node_count, 1))
    gates = cuda.device_array((count, 1, 3))
    trace = cuda.device_array((steps, count, 1, 4))
    voltage_trace = cuda.device_array((steps, count, 1))
    currents = cuda.to_device(np.zeros((steps, count, 1)))
    flags = cuda.to_device(np.zeros(1, dtype=np.int32))

    def launch(start, end):
        batched[1, 64](*buffers, fixed_diagonal, diagonal, rhs, voltage, gates, flags, inverses,
                       trace, voltage_trace, currents, 0.025, 1, 0, start, end)

    execute_windows(total_steps=steps - 1, window_steps=window_steps, launch=launch,
                    synchronize=cuda.synchronize, read_flags=flags.copy_to_host, cell_ids=[0],
                    progress=progress, check_cancelled=check_cancelled)
    state = trace.copy_to_host()[:, :, 0, :]
    current = currents.copy_to_host()[:, :, 0]
    if not np.isfinite(state).all() or not np.isfinite(current).all():
        raise ValueError('Non-finite GPU result')
    return {'time_ms': np.arange(steps) * .025, 'voltage_mv': state[:, :, 0].T,
            'membrane_current_na': current.T}
