"""Experimental CUDA solver for independent, prepared heterogeneous cells."""

import time

import numpy as np

from .batching import estimate_output_bytes
from .events import refined_segment_events
from .execution import execute_windows
from .packing import pack_trees
from .packing_cache import PackedTreeCache


def _final_segment_voltages(final, packed, batch):
    values = [final[packed.segment_nodes[:int(packed.lengths[index]), index], index]
              for index in range(batch)]
    if not all(np.isfinite(value).all() for value in values):
        raise ValueError('Non-finite final GPU voltage')
    return values


def build_cell_major(cells, geometries):
    """Pack one batch for the cell-major kernels, or (None, None, None).

    Returns None when the batch has mixed initial states, which those kernels
    cannot express because they take the initial voltage and the three gates as
    SCALARS. Kept separate from the solve so a caller can pack on a producer
    thread: packing a 3 000-cell batch cost 73 s of the 475 s full-population
    run, all of it serialised in front of the launch.
    """
    from .tree_levels import _parent_array, tree_layouts
    from .warp_packing import pack_cell_major

    voltages = {cell["initial_voltage_mv"] for cell in cells}
    gate_rows = {tuple(float(value) for value in cell["initial_gates"]) for cell in cells}
    if len(voltages) != 1 or len(gate_rows) != 1:
        return None, None, None
    initial_voltage = voltages.pop()
    initial_gates = np.array(gate_rows.pop(), dtype=np.float64)
    trees = [(geometry["parents"], geometry["conductances"], geometry["segment_nodes"],
              np.asarray(geometry["area"], dtype=np.float64),
              np.asarray(cell["field_current_na"], dtype=np.float64))
             for cell, geometry in zip(cells, geometries, strict=True)]
    layouts = [tree_layouts(_parent_array(geometry["parents"]))[0]
               for geometry in geometries]
    return (pack_cell_major(trees, layouts, gates=initial_gates,
                            initial_voltage=initial_voltage),
            initial_voltage, initial_gates)


def _solve_cell_major(cells, geometries, stimulus, table, *, steps, dt_ms, cell_warps,
                      allow_table_clamp, check_cancelled, timing_sink, output_budget_bytes,
                      block_cell_segments=40000, block_cell_threads=512, packed=None,
                      device_window_sink=None, recording_coefficients=None,
                      selected_indices=None, window_steps=25, progress=None):
    """Solve a batch on the cell-major warp kernel (one warp per cell).

    The production kernel keeps every column as (node, cell); a lane stride then
    walks ACROSS cells, so consecutive addresses belong to different cells. This
    path packs (cell, node) instead and gives each cell one WARP, which measured
    2.06x the node-major kernel on the same reduced trees (512 real cells,
    811 203 segments: 112.7e6 vs 54.7e6 live segment-steps/s).

    An optional reduced window sink receives a differential recording and
    selected segment voltages. The current implementation launches the Hines
    and observation kernels once per step; it is experimental and its speed
    has not been established. Full segment traces are not produced.
    """
    from numba import cuda

    from .hines_kernel import block_cell, warp_batched

    batch = len(cells)
    stage_start = time.perf_counter()
    if packed is None:
        packed, initial_voltage, initial_gates = build_cell_major(cells, geometries)
    else:
        voltages = {cell["initial_voltage_mv"] for cell in cells}
        gate_rows = {tuple(float(value) for value in cell["initial_gates"]) for cell in cells}
        initial_voltage = voltages.pop() if len(voltages) == 1 else None
        initial_gates = (np.array(gate_rows.pop(), dtype=np.float64)
                         if len(gate_rows) == 1 else None)
    if packed is None or initial_voltage is None or initial_gates is None:
        # The warp kernel takes the initial state as scalars. Mixed initial
        # states must use the generic kernel instead of dereferencing an absent
        # packing or silently replacing the individual initial states.
        return None
    if timing_sink is not None:
        timing_sink('pack_cell_major', time.perf_counter() - stage_start)
    stage_start = time.perf_counter()
    # The generic guard charges (samples, segments, cell) trajectory columns,
    # which THIS path never allocates: it keeps only final voltages. Charging
    # them capped the cell-major batches far below the device limit and threw
    # "GPU output buffers exceed the supplied budget" for a 4 096-cell batch that
    # actually needs 1.0 GB. Budget the real allocations instead: four
    # (batch, node_slots) fp64 working columns plus the (batch, segment_slots, 3)
    # gate block, all of which the packing has already sized.
    node_slots = int(packed.node_slots)
    segment_slots = int(packed.segment_slots)
    state_bytes = 4 * node_slots * 8 + 3 * segment_slots * 8
    if state_bytes * batch > output_budget_bytes:
        raise ValueError("GPU output buffers exceed the supplied budget")

    mapped_events = []
    for cell, geometry in zip(cells, geometries, strict=True):
        grid = geometry.get("grid")
        count = int(np.asarray(geometry["segment_nodes"]).size)
        if grid is None and not cell["events"]:
            mapped_events.append([])
        else:
            if not isinstance(grid, list) or len(grid) != count:
                raise ValueError("Invalid prepared cell")
            mapped_events.append(refined_segment_events(
                cell["events"], grid, duration_ms=(steps - 1) * dt_ms))
    max_events = max(1, *(len(events) for events in mapped_events))
    event_arrays = {
        key: np.zeros((max_events, batch), dtype=dtype)
        for key, dtype in (
            ("time_ms", np.float64),
            ("weight_us", np.float64),
            ("segment_index", np.int64),
            ("reversal_mv", np.float64),
            ("tau1_ms", np.float64),
            ("tau2_ms", np.float64),
        )
    }
    event_counts = np.zeros(batch, dtype=np.int64)
    for index, events in enumerate(mapped_events):
        event_counts[index] = len(events)
        for position, event in enumerate(events):
            for key, array in event_arrays.items():
                array[position, index] = event[key]

    node_shape = (batch, int(packed.node_slots))
    device = cuda.to_device
    d_conductance = device(packed.conductances)
    d_segment_node = device(packed.segment_nodes)
    d_area = device(packed.area)
    d_field = device(packed.field)
    d_lengths = device(packed.lengths)
    d_nodes = device(packed.nodes)
    d_level_bounds = device(packed.level_bounds)
    d_group_parents = device(packed.group_parents)
    d_group_offsets = device(packed.group_offsets)
    d_group_children = device(packed.group_children)
    d_level_counts = device(packed.level_counts)
    d_fixed = device(packed.fixed_diagonal)
    d_initial_gates = device(initial_gates)
    d_table = device(np.asarray(table, dtype=np.float64))
    d_drive = device(np.zeros(steps, dtype=np.float64))
    d_stimulus = device(np.asarray(stimulus, dtype=np.float64))
    event_devices = [device(array) for array in event_arrays.values()]
    d_event_counts = device(event_counts)
    d_diagonal, d_rhs, d_voltage, d_inverses = (cuda.device_array(node_shape) for _ in range(4))
    d_gates = cuda.device_array((batch, int(packed.segment_slots), 3))
    d_flags = device(np.zeros(batch, dtype=np.int32))
    # A warp gives every cell 32 lanes regardless of width. A 144 870-segment
    # cell measured 3.2e6 live segment-steps/s on one warp against 3.7e7 with a
    # whole block, because its dependent level chain cannot use 32 lanes, so the
    # extreme tail goes to the block-per-cell kernel on the SAME packing.
    widest = int(packed.lengths.max())
    use_block = widest > block_cell_segments
    if use_block:
        blocks, threads = batch, block_cell_threads
    else:
        blocks = (batch + cell_warps - 1) // cell_warps
        threads = 32 * cell_warps
    if timing_sink is not None:
        cuda.synchronize()
        timing_sink('device_allocation_transfer', time.perf_counter() - stage_start)
    stage_start = time.perf_counter()

    kernel = block_cell if use_block else warp_batched

    def launch(start, end):
        kernel[blocks, threads](
            d_table, d_drive, d_stimulus, d_conductance, d_segment_node, d_area, d_field,
            initial_voltage, d_initial_gates, d_lengths, d_nodes, d_level_bounds,
            d_group_parents, d_group_offsets, d_group_children, d_level_counts, d_fixed,
            d_diagonal, d_rhs, d_voltage, d_gates, d_flags, d_inverses,
            *event_devices, d_event_counts, dt_ms, start if start else 0, end)

    if device_window_sink is None:
        execute_windows(total_steps=steps - 1, window_steps=steps - 1, launch=launch,
                        synchronize=cuda.synchronize, read_flags=d_flags.copy_to_host,
                        cell_ids=[cell["id"] for cell in cells],
                        check_cancelled=check_cancelled,
                        allow_table_clamp=allow_table_clamp)
    else:
        from .observation_kernel import record_node_projection
        from .observation_projection import nodal_recording_projection

        ids = [cell['id'] for cell in cells]
        if (not isinstance(recording_coefficients, dict) or not isinstance(selected_indices, dict)
                or list(recording_coefficients) != ids or list(selected_indices) != ids):
            raise ValueError('Invalid GPU recording selection')
        max_selected = max(1, *(len(selected_indices[body])
                                if isinstance(selected_indices[body], list) else 0 for body in ids))
        samples = min(steps, window_steps + 1)
        extra_bytes = batch * (node_slots * 8 + max_selected * 8 + 16
                               + samples * (max_selected + 1) * 8)
        if state_bytes * batch + extra_bytes > output_budget_bytes:
            raise ValueError('GPU output buffers exceed the supplied budget')
        weights = np.zeros(node_shape, dtype=np.float64)
        factors = np.zeros(batch, dtype=np.float64)
        selected_nodes = np.zeros((max_selected, batch), dtype=np.int64)
        selected_counts = np.zeros(batch, dtype=np.int64)
        for index, (cell, geometry) in enumerate(zip(cells, geometries, strict=True)):
            body = cell['id']
            chosen = selected_indices[body]
            count = len(geometry['segment_nodes'])
            if (not isinstance(chosen, list)
                    or any(type(value) is not int or not 0 <= value < count for value in chosen)
                    or len(chosen) != len(set(chosen))):
                raise ValueError('Invalid GPU recording selection')
            row, factors[index] = nodal_recording_projection(
                geometry['parents'], geometry['conductances'], geometry['segment_nodes'],
                recording_coefficients[body], cell['field_current_na'])
            weights[index, :len(row)] = row
            selected_counts[index] = len(chosen)
            selected_nodes[:len(chosen), index] = np.asarray(geometry['segment_nodes'])[chosen]
        d_weights, d_factors, d_selected_nodes, d_selected_counts = (
            device(value) for value in (weights, factors, selected_nodes, selected_counts))
        # Sample zero follows the existing kernel convention: no current, while
        # selected segment voltages are the initial membrane voltage.
        d_signal = device(np.zeros((samples, batch), dtype=np.float64))
        d_selected = device(np.full((samples, max_selected, batch), initial_voltage,
                                    dtype=np.float64))

        def launch_recorded(start, end):
            for step in range(start + 1, end + 1):
                launch(step - 1, step)
                record_node_projection[batch, 128](
                    d_voltage, d_weights, d_nodes, d_factors, stimulus[step],
                    d_selected_nodes, d_selected_counts, step - start, d_signal, d_selected)

        def deliver(end, total):
            start = ((end - 1) // window_steps) * window_steps
            first = 0 if start == 0 else 1
            last = end - start + 1
            signals = d_signal[first:last].copy_to_host()
            selected = d_selected[first:last].copy_to_host()
            rows = [{'id': body, 'neural_uv': signals[:, index],
                     'selected_voltage_mv': selected[:, :selected_counts[index], index].T}
                    for index, body in enumerate(ids)]
            if any(not np.isfinite(row['neural_uv']).all()
                   or not np.isfinite(row['selected_voltage_mv']).all() for row in rows):
                raise ValueError('Non-finite reduced GPU result')
            device_window_sink(start + first, end + 1, rows)
            if progress is not None:
                progress(end, total)

        execute_windows(total_steps=steps - 1, window_steps=window_steps,
                        launch=launch_recorded, synchronize=cuda.synchronize,
                        read_flags=d_flags.copy_to_host, cell_ids=ids, progress=deliver,
                        check_cancelled=check_cancelled, allow_table_clamp=allow_table_clamp)
    if timing_sink is not None:
        timing_sink('solve_cell_major', time.perf_counter() - stage_start)
        stage_start = time.perf_counter()
    final = d_voltage.copy_to_host()
    if timing_sink is not None:
        timing_sink('final_transfer', time.perf_counter() - stage_start)
    values = [final[index, np.asarray(geometry["segment_nodes"])]
              for index, geometry in enumerate(geometries)]
    if not all(np.isfinite(value).all() for value in values):
        raise ValueError("Non-finite final GPU voltage")
    flags = d_flags.copy_to_host()
    return {'time_ms': np.arange(steps) * dt_ms, 'final_voltage_mv': values,
            'table_clamped_cell_ids': [cell["id"] for cell, flag
                                       in zip(cells, flags, strict=True) if flag == 1]}


def solve_prepared_batch(
    cells,
    stimulus_midpoint,
    rate_table,
    *,
    output_budget_bytes,
    dt_ms=0.025,
    allow_table_clamp=False,
    window_steps=25,
    progress=None,
    check_cancelled=None,
    window_sink=None,
    timing_sink=None,
    packing_cache=None,
    device_window_sink=None,
    recording_coefficients=None,
    selected_indices=None,
    reduce_trees=False,
    block_threads=64,
    record_traces=True,
    cell_major=False,
    cell_warps=1,
    block_cell_segments=40000,
    cell_major_packed=None,
    cell_major_block_threads=512,
):
    """Solve independent cells under one common pulse at the selected fixed step.

    Each cell contains ``id``, ``geometry``, ``field_current_na``, ``events``,
    ``initial_voltage_mv`` and three ``initial_gates``. Output contains all
    segment currents, time-resolved voltages and final voltages for all cells. The output
    budget excludes all other GPU allocations; it is not a VRAM reservation.
    No synaptic coupling between cells or biological validation is implied.

    If ``window_sink`` is supplied, it receives ``(start, end, rows)`` for
    consecutive non-overlapping sample slices; rows contain per-cell voltage
    and current arrays. The sink must consume or persist each slice itself.
    The return value then contains final voltages rather than complete traces.
    Optional packing_cache is process-local; its budget excludes Python and
    CUDA overhead and does not constitute a device-memory reservation.
    """
    if (
        type(allow_table_clamp) is not bool
        or dt_ms not in (0.025, 0.05)
        or type(dt_ms) not in (int, float)
        or not isinstance(cells, list)
        or not cells
        or type(output_budget_bytes) is not int
        or output_budget_bytes < 1
        or (window_sink is not None and not callable(window_sink))
        or (timing_sink is not None and not callable(timing_sink))
        or (packing_cache is not None and not isinstance(packing_cache, PackedTreeCache))
        or (device_window_sink is not None and not callable(device_window_sink))
        or (device_window_sink is not None and window_sink is not None)
        or (device_window_sink is None
            and (recording_coefficients is not None or selected_indices is not None))
        or type(window_steps) is not int or window_steps < 1
        or any(not isinstance(cell, dict) for cell in cells)
        or type(reduce_trees) is not bool
        or type(block_threads) is not int or block_threads not in (32, 64, 96, 128, 256)
        or type(record_traces) is not bool
        or (not record_traces and (window_sink is not None or device_window_sink is not None))
        or type(cell_major) is not bool
        or type(cell_warps) is not int or cell_warps not in (1, 2, 4, 8)
        or type(block_cell_segments) is not int or block_cell_segments < 1
        or type(cell_major_block_threads) is not int
        or cell_major_block_threads not in (32, 64, 128, 256, 512)
        or (cell_major_packed is not None
            and (not cell_major or type(cell_major_packed) is not tuple
                 or len(cell_major_packed) != 3))
        or (cell_major and (window_sink is not None
                            or (record_traces and device_window_sink is None)))
    ):
        raise ValueError("Invalid GPU batch")
    ids = [cell.get("id") for cell in cells]
    if any(type(cell_id) is not int or cell_id <= 0 for cell_id in ids) or len(set(ids)) != len(
        ids
    ):
        raise ValueError("Cell IDs must be unique positive integers")
    stimulus = np.asarray(stimulus_midpoint, dtype=np.float64)
    table = np.asarray(rate_table, dtype=np.float64)
    if (
        stimulus.ndim != 1
        or len(stimulus) < 2
        or stimulus[0] != 0
        or not np.isfinite(stimulus).all()
        or table.shape != (201, 6)
        or not np.isfinite(table).all()
        or np.any(table[:, 1::2] <= 0)
    ):
        raise ValueError("Invalid common GPU inputs")
    stage_start = time.perf_counter()
    geometries = [cell["geometry"] for cell in cells]
    if reduce_trees:
        from .reduced_tree import reduce_geometry

        geometries = [reduce_geometry(g, verify=False)[0] for g in geometries]
    if cell_major:
        solved = _solve_cell_major(
            cells, geometries, stimulus, table, steps=len(stimulus), dt_ms=dt_ms,
            cell_warps=cell_warps, allow_table_clamp=allow_table_clamp,
            check_cancelled=check_cancelled, timing_sink=timing_sink,
            output_budget_bytes=output_budget_bytes,
            block_cell_segments=block_cell_segments,
            block_cell_threads=cell_major_block_threads,
            packed=None if cell_major_packed is None else cell_major_packed[0],
            device_window_sink=device_window_sink,
            recording_coefficients=recording_coefficients, selected_indices=selected_indices,
            window_steps=window_steps, progress=progress)
        if solved is not None:
            return solved
    trees = [(g["parents"], g["conductances"], g["segment_nodes"]) for g in geometries]
    packed = pack_trees(trees) if packing_cache is None else packing_cache.get_or_pack(trees)
    if timing_sink is not None:
        timing_sink('pack_trees', time.perf_counter() - stage_start)
    stage_start = time.perf_counter()
    batch = len(cells)
    steps = len(stimulus)
    max_segments = int(packed.lengths.max())
    streaming = window_sink is not None or device_window_sink is not None
    buffer_samples = min(steps, window_steps + 1) if streaming else steps
    if device_window_sink is not None:
        if (not isinstance(recording_coefficients, dict) or not isinstance(selected_indices, dict)
                or list(recording_coefficients) != ids or list(selected_indices) != ids):
            raise ValueError('Invalid GPU recording selection')
        for index, body in enumerate(ids):
            coeff = np.asarray(recording_coefficients[body], dtype=float)
            chosen = selected_indices[body]
            if (coeff.shape != (int(packed.lengths[index]),) or not np.isfinite(coeff).all()
                    or not isinstance(chosen, list)
                    or any(type(value) is not int or not 0 <= value < len(coeff)
                           for value in chosen)
                    or len(chosen) != len(set(chosen))):
                raise ValueError('Invalid GPU recording selection')
        max_selected = max(1, *(len(selected_indices[body]) for body in ids))
        reduction_bytes = buffer_samples * batch * (max_selected + 1) * 8
    else:
        reduction_bytes = 0
    if estimate_output_bytes(max_segments=max_segments, batch_size=batch, samples=buffer_samples,
                             state_trace_cells=0)[
        "total"
    ] + reduction_bytes > output_budget_bytes:
        raise ValueError("GPU output buffers exceed the supplied budget")
    area = np.zeros((max_segments, batch))
    field = np.zeros_like(area)
    initial = np.zeros((max_segments, batch, 4))
    mapped_events = []
    for cell_index, (cell, geometry) in enumerate(zip(cells, geometries, strict=True)):
        count = int(packed.lengths[cell_index])
        cell_area = np.asarray(geometry["area"], dtype=np.float64)
        cell_field = np.asarray(cell["field_current_na"], dtype=np.float64)
        gates = np.asarray(cell["initial_gates"], dtype=np.float64)
        voltage = cell["initial_voltage_mv"]
        # A grid is only needed to place synaptic events. Cells without events
        # may omit it entirely, which lets a bulk prepare hand over flat arrays
        # without materialising one Python tuple per segment.
        grid = geometry.get("grid")
        gridless = grid is None and not cell["events"]
        if (
            (not gridless and not isinstance(grid, list))
            or (not gridless and len(grid) != count)
            or cell_area.shape != (count,)
            or np.any(cell_area <= 0)
            or cell_field.shape != (count,)
            or gates.shape != (3,)
            or np.any(gates < 0)
            or np.any(gates > 1)
            or isinstance(voltage, bool)
            or not isinstance(voltage, int | float)
            or not np.isfinite(voltage)
            or not -100 <= voltage <= 100
            or any(not np.isfinite(value).all() for value in (cell_area, cell_field, gates))
        ):
            raise ValueError("Invalid prepared cell")
        area[:count, cell_index] = cell_area
        field[:count, cell_index] = cell_field
        initial[:count, cell_index, 0] = voltage
        initial[:count, cell_index, 1:] = gates
        mapped_events.append(
            refined_segment_events(
                cell["events"], grid, duration_ms=(steps - 1) * dt_ms
            ) if not gridless else []
        )
    max_events = max(1, *(len(events) for events in mapped_events))
    event_arrays = {
        key: np.zeros((max_events, batch), dtype=dtype)
        for key, dtype in (
            ("time_ms", np.float64),
            ("weight_us", np.float64),
            ("segment_index", np.int64),
            ("reversal_mv", np.float64),
            ("tau1_ms", np.float64),
            ("tau2_ms", np.float64),
        )
    }
    event_counts = np.zeros(batch, dtype=np.int64)
    for cell_index, events in enumerate(mapped_events):
        event_counts[cell_index] = len(events)
        for event_index, event in enumerate(events):
            for key, array in event_arrays.items():
                array[event_index, cell_index] = event[key]

    if timing_sink is not None:
        timing_sink('prepare_arrays', time.perf_counter() - stage_start)
    stage_start = time.perf_counter()

    from numba import cuda

    from .hines_kernel import batched, static_diagonal

    arrays = [
        table,
        np.zeros(steps),
        stimulus,
        packed.parents,
        packed.conductances,
        packed.segment_nodes,
        area,
        field,
        initial,
        *event_arrays.values(),
        event_counts,
        packed.lengths,
        packed.nodes,
        packed.node_segments,
        packed.level_bounds,
        packed.group_parents,
        packed.group_offsets,
        packed.group_children,
        packed.child_offsets,
        packed.child_indices,
        packed.level_counts,
    ]
    buffers = [cuda.to_device(value) for value in arrays]
    node_shape = packed.parents.shape
    fixed_diagonal = cuda.device_array(node_shape)
    static_diagonal[batch, block_threads](buffers[4], buffers[17], buffers[-3], buffers[-2],
                                          fixed_diagonal)
    diagonal, rhs, voltage, inverses = (cuda.device_array(node_shape) for _ in range(4))
    gates = cuda.device_array((max_segments, batch, 3))
    # Gate histories are not returned by this solver; retain only live gates.
    trace = cuda.device_array((1, 1, 1, 4))
    if record_traces:
        voltage_trace = cuda.to_device(np.zeros((buffer_samples, max_segments, batch)))
        currents = cuda.to_device(np.zeros((buffer_samples, max_segments, batch)))
    else:
        # One-element stand-ins: the kernel only touches these when record is
        # True. Two (samples, segments, batch) fp64 arrays cost 416 B per segment
        # slot and are what caps the batch below GPU saturation.
        voltage_trace = cuda.device_array((1, 1, 1))
        currents = cuda.device_array((1, 1, 1))
    flags = cuda.to_device(np.zeros(batch, dtype=np.int32))
    if device_window_sink is not None:
        from .recording_kernel import gather_window_voltages, reduce_window_currents

        coefficients = np.zeros((max_segments, batch), dtype=np.float64)
        selection = np.zeros((max_selected, batch), dtype=np.int64)
        selection_counts = np.zeros(batch, dtype=np.int64)
        for index, body in enumerate(ids):
            coefficients[:int(packed.lengths[index]), index] = recording_coefficients[body]
            chosen = selected_indices[body]
            selection_counts[index] = len(chosen)
            selection[:len(chosen), index] = chosen
        d_coefficients = cuda.to_device(coefficients)
        d_reduction_lengths = cuda.to_device(packed.lengths)
        d_selection = cuda.to_device(selection)
        d_selection_counts = cuda.to_device(selection_counts)
        d_reduced = cuda.device_array((buffer_samples, batch), dtype=np.float64)
        d_selected = cuda.device_array((buffer_samples, max_selected, batch), dtype=np.float64)
    if timing_sink is not None:
        cuda.synchronize()
        timing_sink('device_allocation_transfer', time.perf_counter() - stage_start)
    stage_start = time.perf_counter()
    window_seconds = 0.

    def launch(start, end):
        batched[batch, block_threads](
            *buffers, fixed_diagonal, diagonal, rhs, voltage, gates, flags, inverses, trace,
            voltage_trace, currents, dt_ms, 0, start if streaming else 0, start, end,
            record_traces,
        )

    def after_window(end, total):
        nonlocal window_seconds
        window_start = time.perf_counter()
        if streaming:
            start = ((end - 1) // window_steps) * window_steps
            first = 0 if start == 0 else 1
            last = end - start + 1
            if device_window_sink is not None:
                sample_count = last - first
                reduce_window_currents[(sample_count, batch), 128](
                    currents[first:last], d_coefficients, d_reduction_lengths,
                    d_reduced[:sample_count])
                gather_window_voltages[((max_selected + 127) // 128, sample_count, batch), 128](
                    voltage_trace[first:last], d_selection, d_selection_counts,
                    d_selected[:sample_count])
                cuda.synchronize()
                reduced = d_reduced[:sample_count].copy_to_host()
                chosen = d_selected[:sample_count].copy_to_host()
                rows = [{'id': body, 'neural_uv': reduced[:, index],
                         'selected_voltage_mv': chosen[:, :selection_counts[index], index].T}
                        for index, body in enumerate(ids)]
                if any(not np.isfinite(row['neural_uv']).all()
                       or not np.isfinite(row['selected_voltage_mv']).all() for row in rows):
                    raise ValueError('Non-finite reduced GPU result')
                device_window_sink(start + first, end + 1, rows)
            else:
                v = voltage_trace[first:last].copy_to_host()
                i = currents[first:last].copy_to_host()
                if not np.isfinite(v).all() or not np.isfinite(i).all():
                    raise ValueError('Non-finite GPU result')
                rows = [{'id': cell_id,
                         'voltage_mv': v[:, :int(packed.lengths[index]), index].T,
                         'membrane_current_na': i[:, :int(packed.lengths[index]), index].T}
                        for index, cell_id in enumerate(ids)]
                window_sink(start + first, end + 1, rows)
        if progress is not None:
            progress(end, total)
        window_seconds += time.perf_counter() - window_start

    execute_windows(
        total_steps=steps - 1,
        window_steps=window_steps,
        launch=launch,
        synchronize=cuda.synchronize,
        read_flags=flags.copy_to_host,
        cell_ids=ids,
        progress=after_window if streaming or progress is not None else None,
        check_cancelled=check_cancelled,
        allow_table_clamp=allow_table_clamp,
    )
    if timing_sink is not None:
        timing_sink('solve_and_window_callbacks', time.perf_counter() - stage_start)
        timing_sink('window_callbacks', window_seconds)
    stage_start = time.perf_counter()
    final = voltage.copy_to_host()
    if timing_sink is not None:
        timing_sink('final_transfer', time.perf_counter() - stage_start)
    if streaming:
        final_segments = _final_segment_voltages(final, packed, batch)
        return {'time_ms': np.arange(steps) * dt_ms,
                'final_voltage_mv': final_segments,
                'table_clamped_cell_ids': [ids[i] for i, flag in enumerate(flags.copy_to_host())
                                           if flag == 1]}
    if not record_traces:
        # Trajectory recording was disabled for this solve, so only the final
        # state exists; asking for per-sample currents would hand back garbage.
        final_segments = _final_segment_voltages(final, packed, batch)
        return {'time_ms': np.arange(steps) * dt_ms,
                'final_voltage_mv': final_segments,
                'table_clamped_cell_ids': [ids[i] for i, flag in enumerate(flags.copy_to_host())
                                           if flag == 1]}
    raw_currents, raw_voltages = currents.copy_to_host(), voltage_trace.copy_to_host()
    if not all(np.isfinite(value).all() for value in (raw_currents, raw_voltages)):
        raise ValueError("Non-finite GPU result")
    results = []
    for index, cell_id in enumerate(ids):
        count = int(packed.lengths[index])
        cell_current = raw_currents[:, :count, index].T
        cell_voltage = raw_voltages[:, :count, index].T
        final_voltage = final[packed.segment_nodes[:count, index], index]
        if not np.isfinite(final_voltage).all():
            raise ValueError("Non-finite GPU result")
        results.append(
            {
                "id": cell_id,
                "membrane_current_na": cell_current,
                "voltage_mv": cell_voltage,
                "final_voltage_mv": final_voltage,
            }
        )
    return {"time_ms": np.arange(steps) * dt_ms, "cells": results,
            "table_clamped_cell_ids": [ids[i] for i, flag in enumerate(flags.copy_to_host())
                                       if flag == 1]}
