"""Experimental cell-major Hines kernel with fused reduced recording.

Derived from hines_kernel.warp_batched; compare both when changing the solver.
This kernel does not establish biological validity.
"""

import math

from numba import cuda, float64


@cuda.jit
def warp_batched_recorded(
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
    observation_weights, observation_factors, selected_nodes, selected_counts,
    signal, selected,
):
    """Experimental warp Hines solve with fused reduced recording.

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
        # Accumulate each cell's nodal recording within its owning warp.
        # Each warp owns a disjoint 32-slot slice, including in partial blocks.
        scratch = cuda.shared.array(256, dtype=float64)
        lane_sum = 0.0
        for node in range(lane, n, 32):
            # Axial projection weights sum to zero; remove common voltage
            # before reduction to avoid cancellation of large resting terms.
            lane_sum += observation_weights[cell, node] * (voltage[cell, node] - initial_voltage)
        scratch[cuda.threadIdx.x] = lane_sum
        cuda.syncwarp()
        offset = 16
        while offset:
            if lane < offset:
                scratch[cuda.threadIdx.x] += scratch[cuda.threadIdx.x + offset]
            cuda.syncwarp()
            offset //= 2
        if lane == 0:
            signal[step - start_step, cell] = (scratch[cuda.threadIdx.x]
                + observation_factors[cell] * midpoint)
        for index in range(lane, selected_counts[cell], 32):
            selected[step - start_step, index, cell] = voltage[cell, selected_nodes[index, cell]]
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
def block_cell_recorded(
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
    observation_weights, observation_factors, selected_nodes, selected_counts,
    signal, selected,
):
    """Experimental block Hines solve with fused reduced recording.

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
        # Reduce the nodal observation inside the same cell block.
        scratch = cuda.shared.array(512, dtype=float64)
        lane_sum = 0.0
        for node in range(lane, n, stride):
            lane_sum += observation_weights[cell, node] * (voltage[cell, node] - initial_voltage)
        scratch[lane] = lane_sum
        cuda.syncthreads()
        offset = stride // 2
        while offset:
            if lane < offset:
                scratch[lane] += scratch[lane + offset]
            cuda.syncthreads()
            offset //= 2
        if lane == 0:
            signal[step - start_step, cell] = (scratch[0]
                + observation_factors[cell] * midpoint)
        for index in range(lane, selected_counts[cell], stride):
            selected[step - start_step, index, cell] = voltage[cell, selected_nodes[index, cell]]
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
