"""Experimental CUDA Hines kernel; not connected to the service executor.

This research prototype supports 0.025 and 0.05 ms steps and flags
voltages outside the rate-table domain [-100, 100] mV. It records membrane
voltage and current for every cell; gate history is optional.
It does not validate input arrays or implement a coupled network.
The stimulus array contains original-waveform midpoint values at indices 1..N;
index 0 is unused. Endpoint samples must not be averaged across discontinuities.
"""

import math

from numba import cuda


@cuda.jit
def static_diagonal(conductance, nodes, child_offsets, child_indices, result):
    """Sum fixed axial conductances in the same order as the time-step kernel."""
    cell = cuda.blockIdx.x
    lane = cuda.threadIdx.x
    for node in range(lane, nodes[cell], cuda.blockDim.x):
        total = conductance[node, cell] if node > 0 else 0.0
        for idx in range(child_offsets[node, cell], child_offsets[node + 1, cell]):
            total += conductance[child_indices[idx, cell], cell]
        result[node, cell] = total


@cuda.jit
def batched(
    table,
    drive,
    stimulus_midpoint,
    parent,
    conductance,
    segment_node,
    area,
    field,
    initial,
    event_times,
    event_weights,
    event_targets,
    event_reversal,
    event_tau1,
    event_tau2,
    event_counts,
    lengths,
    nodes,
    node_segment,
    level_bounds,
    group_parents,
    group_offsets,
    group_children,
    child_offsets,
    child_indices,
    level_counts,
    fixed_diagonal,
    d,
    rhs,
    voltage,
    gates,
    range_flags,
    inverses,
    trace,
    voltage_trace,
    mem_trace,
    dt_ms,
    trace_cells,
    output_origin,
    start_step,
    end_step,
    record=True,
):
    """One block per cell; every lane walks the levels of that cell tree.

    record is a runtime switch: with the default True the trajectory buffers
(voltage_trace and mem_trace) are filled exactly as before. A bulk reduction
that only needs the final state can pass False, which lets the caller allocate
one-element stand-ins instead of (samples, segments, batch) arrays. Those arrays
cost 416 B per segment slot, which is what otherwise caps the batch at ~1500
cells on a 6 GiB board and starves the GPU, so the switch is worth several
times the throughput.
    """
    cell = cuda.blockIdx.x
    lane = cuda.threadIdx.x
    count = lengths[cell]
    n = nodes[cell]
    if start_step == 0:
        for i in range(lane, count, cuda.blockDim.x):
            node = segment_node[i, cell]
            voltage[node, cell] = initial[i, cell, 0]
            if record:
                voltage_trace[0, i, cell] = initial[i, cell, 0]
            for j in range(3):
                gates[i, cell, j] = initial[i, cell, j + 1]
            if cell < trace_cells:
                for j in range(4):
                    trace[0, i, cell, j] = initial[i, cell, j]
    cuda.syncthreads()
    for step in range(start_step + 1, end_step + 1):
        for node in range(lane, n, cuda.blockDim.x):
            d[node, cell] = fixed_diagonal[node, cell]
            rhs[node, cell] = 0.0
        cuda.syncthreads()
        for i in range(lane, count, cuda.blockDim.x):
            node = segment_node[i, cell]
            v = voltage[node, cell]
            m = gates[i, cell, 0]
            hh = gates[i, cell, 1]
            nn = gates[i, cell, 2]
            gn = 0.12 * m * m * m * hh * area[i, cell] * 0.01
            gk = 0.036 * nn * nn * nn * nn * area[i, cell] * 0.01
            gl = 0.0003 * area[i, cell] * 0.01
            cm = area[i, cell] * 1e-5 / dt_ms
            d[node, cell] += cm + gn + gk + gl
            rhs[node, cell] += (
                cm * v
                + gn * 50.0
                + gk * (-77.0)
                + gl * (-54.3)
                + field[i, cell] * stimulus_midpoint[step]
            )
        cuda.syncthreads()
        if lane == 0:
            for ev in range(event_counts[cell]):
                delivery = math.floor(event_times[ev, cell] / dt_ms + 0.5) * dt_ms
                syn_time = step * dt_ms - delivery - dt_ms
                if syn_time > 0.0:
                    t1 = event_tau1[ev, cell]
                    t2 = event_tau2[ev, cell]
                    peak = t1 * t2 / (t2 - t1) * math.log(t2 / t1)
                    factor = 1.0 / (math.exp(-peak / t2) - math.exp(-peak / t1))
                    sg = (
                        event_weights[ev, cell]
                        * factor
                        * (math.exp(-syn_time / t2) - math.exp(-syn_time / t1))
                    )
                    target = segment_node[event_targets[ev, cell], cell]
                    d[target, cell] += sg
                    rhs[target, cell] += sg * event_reversal[ev, cell]
            rhs[segment_node[0, cell], cell] += drive[step]
        cuda.syncthreads()
        for level in range(level_counts[cell] - 1, -1, -1):
            start = level_bounds[level, cell]
            end = level_bounds[level + 1, cell]
            for group in range(start + lane, end, cuda.blockDim.x):
                p = group_parents[group, cell]
                dd = 0.0
                rr = 0.0
                for k in range(group_offsets[group, cell], group_offsets[group + 1, cell]):
                    node = group_children[k, cell]
                    g = conductance[node, cell]
                    inv = 1.0 / d[node, cell]
                    inverses[node, cell] = inv
                    dd += g * g * inv
                    rr += g * rhs[node, cell] * inv
                d[p, cell] -= dd
                rhs[p, cell] += rr
            cuda.syncthreads()
        if lane == 0:
            inverses[0, cell] = 1.0 / d[0, cell]
            voltage[0, cell] = rhs[0, cell] * inverses[0, cell]
        cuda.syncthreads()
        for level in range(level_counts[cell]):
            start = level_bounds[level, cell]
            end = level_bounds[level + 1, cell]
            for group in range(start + lane, end, cuda.blockDim.x):
                p = group_parents[group, cell]
                for k in range(group_offsets[group, cell], group_offsets[group + 1, cell]):
                    node = group_children[k, cell]
                    voltage[node, cell] = (
                        rhs[node, cell] + conductance[node, cell] * voltage[p, cell]
                    ) * inverses[node, cell]
            cuda.syncthreads()
        if record:
            for i in range(lane, count, cuda.blockDim.x):
                node = segment_node[i, cell]
                value = field[i, cell] * stimulus_midpoint[step]
                if node > 0:
                    p = parent[node, cell]
                    value -= conductance[node, cell] * (voltage[node, cell] - voltage[p, cell])
                for idx in range(child_offsets[node, cell], child_offsets[node + 1, cell]):
                    child = child_indices[idx, cell]
                    value += (conductance[child, cell]
                              * (voltage[child, cell] - voltage[node, cell]))
                mem_trace[step - output_origin, i, cell] = value
            cuda.syncthreads()
        for i in range(lane, count, cuda.blockDim.x):
            v = voltage[segment_node[i, cell], cell]
            if record:
                voltage_trace[step - output_origin, i, cell] = v
            finite_voltage = math.isfinite(v)
            if not finite_voltage:
                cuda.atomic.max(range_flags, cell, 2)
            elif v < -100.0 or v > 100.0:
                cuda.atomic.max(range_flags, cell, 1)
            pos = v + 100.0 if finite_voltage else 0.0
            if pos < 0.0:
                pos = 0.0
            if pos > 200.0:
                pos = 200.0
            low = int(pos)
            high = low + 1 if low < 200 else 200
            f = pos - low
            for j in range(3):
                inf = table[low, 2 * j] + f * (table[high, 2 * j] - table[low, 2 * j])
                tau = table[low, 2 * j + 1] + f * (table[high, 2 * j + 1] - table[low, 2 * j + 1])
                gates[i, cell, j] = inf + (gates[i, cell, j] - inf) * math.exp(-dt_ms / tau)
            if cell < trace_cells:
                trace[step, i, cell, 0] = v
                for j in range(3):
                    trace[step, i, cell, j + 1] = gates[i, cell, j]
        cuda.syncthreads()


# Cells per block for warp_batched. A block of 32 * WARPS_PER_BLOCK threads
# carries WARPS_PER_BLOCK cells, so blocks = ceil(batch / WARPS_PER_BLOCK).
# Measured on 2 048 real reduced cells (seg mean 876): one warp per cell with
# two warps per block was the optimum (9.79e7 live segment-steps/s); eight warps
# per block fell to 8.55e7. The value is read at compile time, so changing it
# requires a recompile (which numba does automatically on the next launch).
WARPS_PER_BLOCK = 2


@cuda.jit
def warp_batched(
    table,
    drive,
    stimulus_midpoint,
    conductance,
    segment_node,
    area,
    field,
    initial_voltage,
    initial_gates,
    lengths,
    nodes,
    level_bounds,
    group_parents,
    group_offsets,
    group_children,
    level_counts,
    fixed_diagonal,
    d,
    rhs,
    voltage,
    gates,
    range_flags,
    inverses,
    event_times,
    event_weights,
    event_targets,
    event_reversal,
    event_tau1,
    event_tau2,
    event_counts,
    dt_ms,
    start_step,
    end_step,
):
    """One WARP per cell over cell-major arrays; bit-identical to batched().

    Two things make this faster than the production block-per-cell kernel:
    1. the arrays are (cell, node) instead of (node, cell), so a lane stride of
       one walks consecutive addresses inside a cell (2.4x on pointwise traffic);
    2. a Hines barrier between levels only has to synchronise the warp that owns
       the cell, so cuda.syncwarp() replaces cuda.syncthreads().

    blocks = ceil(batch / warps), blockDim.x = 32 * warps. The number of warps
    per block is taken from blockDim at RUN time, never from module state: an
    earlier version read a module constant here while the caller passed its own
    thread count, so a launch with 32 threads silently computed only the even
    cells of the batch (cell = 2 * blockIdx) and skipped every odd one.
    """
    cell = cuda.blockIdx.x * (cuda.blockDim.x // 32) + cuda.threadIdx.x // 32
    lane = cuda.threadIdx.x % 32
    if cell >= lengths.shape[0]:
        return
    count = lengths[cell]
    n = nodes[cell]
    if start_step == 0:
        for i in range(lane, count, 32):
            voltage[cell, segment_node[cell, i]] = initial_voltage
            for j in range(3):
                gates[cell, i, j] = initial_gates[j]
    cuda.syncwarp()
    for step in range(start_step + 1, end_step + 1):
        midpoint = stimulus_midpoint[step]
        for node in range(lane, n, 32):
            d[cell, node] = fixed_diagonal[cell, node]
            rhs[cell, node] = 0.0
        cuda.syncwarp()
        for i in range(lane, count, 32):
            node = segment_node[cell, i]
            v = voltage[cell, node]
            m = gates[cell, i, 0]
            hh = gates[cell, i, 1]
            nn = gates[cell, i, 2]
            membrane = area[cell, i]
            gna = 0.12 * m * m * m * hh * membrane * 0.01
            gk = 0.036 * nn * nn * nn * nn * membrane * 0.01
            gl = 0.0003 * membrane * 0.01
            cm = membrane * 1e-5 / dt_ms
            d[cell, node] += cm + gna + gk + gl
            rhs[cell, node] += (
                cm * v
                + gna * 50.0
                + gk * (-77.0)
                + gl * (-54.3)
                + field[cell, i] * midpoint
            )
        cuda.syncwarp()
        if lane == 0:
            # Synaptic events and the drive injection are applied in the same
            # order as batched() so the two kernels stay bit-identical.
            for ev in range(event_counts[cell]):
                delivery = math.floor(event_times[ev, cell] / dt_ms + 0.5) * dt_ms
                syn_time = step * dt_ms - delivery - dt_ms
                if syn_time > 0.0:
                    t1 = event_tau1[ev, cell]
                    t2 = event_tau2[ev, cell]
                    peak = t1 * t2 / (t2 - t1) * math.log(t2 / t1)
                    factor = 1.0 / (math.exp(-peak / t2) - math.exp(-peak / t1))
                    sg = (
                        event_weights[ev, cell]
                        * factor
                        * (math.exp(-syn_time / t2) - math.exp(-syn_time / t1))
                    )
                    target_node = segment_node[cell, event_targets[ev, cell]]
                    d[cell, target_node] += sg
                    rhs[cell, target_node] += sg * event_reversal[ev, cell]
            rhs[cell, segment_node[cell, 0]] += drive[step]
        cuda.syncwarp()
        for level in range(level_counts[cell] - 1, -1, -1):
            start = level_bounds[cell, level]
            end = level_bounds[cell, level + 1]
            for group in range(start + lane, end, 32):
                target = group_parents[cell, group]
                total_d = 0.0
                total_r = 0.0
                for k in range(group_offsets[cell, group],
                               group_offsets[cell, group + 1]):
                    node = group_children[cell, k]
                    g = conductance[cell, node]
                    inv = 1.0 / d[cell, node]
                    inverses[cell, node] = inv
                    total_d += g * g * inv
                    total_r += g * rhs[cell, node] * inv
                d[cell, target] -= total_d
                rhs[cell, target] += total_r
            cuda.syncwarp()
        if lane == 0:
            inverses[cell, 0] = 1.0 / d[cell, 0]
            voltage[cell, 0] = rhs[cell, 0] * inverses[cell, 0]
        cuda.syncwarp()
        for level in range(level_counts[cell]):
            start = level_bounds[cell, level]
            end = level_bounds[cell, level + 1]
            for group in range(start + lane, end, 32):
                target = group_parents[cell, group]
                for k in range(group_offsets[cell, group],
                               group_offsets[cell, group + 1]):
                    node = group_children[cell, k]
                    voltage[cell, node] = (
                        rhs[cell, node]
                        + conductance[cell, node] * voltage[cell, target]
                    ) * inverses[cell, node]
            cuda.syncwarp()
        for i in range(lane, count, 32):
            v = voltage[cell, segment_node[cell, i]]
            if not math.isfinite(v):
                cuda.atomic.max(range_flags, cell, 2)
            elif v < -100.0 or v > 100.0:
                cuda.atomic.max(range_flags, cell, 1)
            pos = v + 100.0 if math.isfinite(v) else 0.0
            if pos < 0.0:
                pos = 0.0
            if pos > 200.0:
                pos = 200.0
            low = int(pos)
            high = low + 1 if low < 200 else 200
            frac = pos - low
            for j in range(3):
                inf = (table[low, 2 * j]
                       + frac * (table[high, 2 * j] - table[low, 2 * j]))
                tau = (table[low, 2 * j + 1]
                       + frac * (table[high, 2 * j + 1] - table[low, 2 * j + 1]))
                gates[cell, i, j] = (inf + (gates[cell, i, j] - inf)
                                     * math.exp(-dt_ms / tau))
        cuda.syncwarp()



@cuda.jit
def block_cell(
    table,
    drive,
    stimulus_midpoint,
    conductance,
    segment_node,
    area,
    field,
    initial_voltage,
    initial_gates,
    lengths,
    nodes,
    level_bounds,
    group_parents,
    group_offsets,
    group_children,
    level_counts,
    fixed_diagonal,
    d,
    rhs,
    voltage,
    gates,
    range_flags,
    inverses,
    event_times,
    event_weights,
    event_targets,
    event_reversal,
    event_tau1,
    event_tau2,
    event_counts,
    dt_ms,
    start_step,
    end_step,
):
    """One BLOCK per cell over cell-major arrays; bit-identical to batched().

    warp_batched gives one cell 32 lanes. That is the best configuration for a
    narrow tree, but a cell with 50 000+ segments has to walk each Hines level
    with 32 lanes and its dependent level chain dominates. This entry point keeps
    the same (cell, node) layout - so the coalescing that made the warp kernel
    fast is preserved - and gives the cell blockDim.x lanes instead.

    blocks = batch; blockDim.x is the caller thread count.
    """
    cell = cuda.blockIdx.x
    lane = cuda.threadIdx.x
    stride = cuda.blockDim.x
    count = lengths[cell]
    n = nodes[cell]
    if start_step == 0:
        for i in range(lane, count, stride):
            voltage[cell, segment_node[cell, i]] = initial_voltage
            for j in range(3):
                gates[cell, i, j] = initial_gates[j]
    cuda.syncthreads()
    for step in range(start_step + 1, end_step + 1):
        midpoint = stimulus_midpoint[step]
        for node in range(lane, n, stride):
            d[cell, node] = fixed_diagonal[cell, node]
            rhs[cell, node] = 0.0
        cuda.syncthreads()
        for i in range(lane, count, stride):
            node = segment_node[cell, i]
            v = voltage[cell, node]
            m = gates[cell, i, 0]
            hh = gates[cell, i, 1]
            nn = gates[cell, i, 2]
            membrane = area[cell, i]
            gna = 0.12 * m * m * m * hh * membrane * 0.01
            gk = 0.036 * nn * nn * nn * nn * membrane * 0.01
            gl = 0.0003 * membrane * 0.01
            cm = membrane * 1e-5 / dt_ms
            d[cell, node] += cm + gna + gk + gl
            rhs[cell, node] += (
                cm * v
                + gna * 50.0
                + gk * (-77.0)
                + gl * (-54.3)
                + field[cell, i] * midpoint
            )
        cuda.syncthreads()
        if lane == 0:
            for ev in range(event_counts[cell]):
                delivery = math.floor(event_times[ev, cell] / dt_ms + 0.5) * dt_ms
                syn_time = step * dt_ms - delivery - dt_ms
                if syn_time > 0.0:
                    t1 = event_tau1[ev, cell]
                    t2 = event_tau2[ev, cell]
                    peak = t1 * t2 / (t2 - t1) * math.log(t2 / t1)
                    factor = 1.0 / (math.exp(-peak / t2) - math.exp(-peak / t1))
                    sg = (
                        event_weights[ev, cell]
                        * factor
                        * (math.exp(-syn_time / t2) - math.exp(-syn_time / t1))
                    )
                    target_node = segment_node[cell, event_targets[ev, cell]]
                    d[cell, target_node] += sg
                    rhs[cell, target_node] += sg * event_reversal[ev, cell]
            rhs[cell, segment_node[cell, 0]] += drive[step]
        cuda.syncthreads()
        for level in range(level_counts[cell] - 1, -1, -1):
            start = level_bounds[cell, level]
            end = level_bounds[cell, level + 1]
            for group in range(start + lane, end, stride):
                target = group_parents[cell, group]
                total_d = 0.0
                total_r = 0.0
                for k in range(group_offsets[cell, group],
                               group_offsets[cell, group + 1]):
                    node = group_children[cell, k]
                    g = conductance[cell, node]
                    inv = 1.0 / d[cell, node]
                    inverses[cell, node] = inv
                    total_d += g * g * inv
                    total_r += g * rhs[cell, node] * inv
                d[cell, target] -= total_d
                rhs[cell, target] += total_r
            cuda.syncthreads()
        if lane == 0:
            inverses[cell, 0] = 1.0 / d[cell, 0]
            voltage[cell, 0] = rhs[cell, 0] * inverses[cell, 0]
        cuda.syncthreads()
        for level in range(level_counts[cell]):
            start = level_bounds[cell, level]
            end = level_bounds[cell, level + 1]
            for group in range(start + lane, end, stride):
                target = group_parents[cell, group]
                for k in range(group_offsets[cell, group],
                               group_offsets[cell, group + 1]):
                    node = group_children[cell, k]
                    voltage[cell, node] = (
                        rhs[cell, node]
                        + conductance[cell, node] * voltage[cell, target]
                    ) * inverses[cell, node]
            cuda.syncthreads()
        for i in range(lane, count, stride):
            v = voltage[cell, segment_node[cell, i]]
            if not math.isfinite(v):
                cuda.atomic.max(range_flags, cell, 2)
            elif v < -100.0 or v > 100.0:
                cuda.atomic.max(range_flags, cell, 1)
            pos = v + 100.0 if math.isfinite(v) else 0.0
            if pos < 0.0:
                pos = 0.0
            if pos > 200.0:
                pos = 200.0
            low = int(pos)
            high = low + 1 if low < 200 else 200
            frac = pos - low
            for j in range(3):
                inf = (table[low, 2 * j]
                       + frac * (table[high, 2 * j] - table[low, 2 * j]))
                tau = (table[low, 2 * j + 1]
                       + frac * (table[high, 2 * j + 1] - table[low, 2 * j + 1]))
                gates[cell, i, j] = (inf + (gates[cell, i, j] - inf)
                                     * math.exp(-dt_ms / tau))
        cuda.syncthreads()
