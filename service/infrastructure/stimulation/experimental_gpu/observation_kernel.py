"""Device-side reduction for cell-major recording at one simulated sample.

The caller owns array validation, the initial-sample convention, and ordered
window delivery. This kernel does not simulate cells or biological coupling.
"""

from numba import cuda, float64


@cuda.jit
def record_node_projection(voltage, weights, node_counts, field_factors, stimulus,
                           selected_nodes, selection_counts, sample, signal, selected):
    """Reduce each cell's node projection and gather selected node voltages.

    Launch one block per cell with a power-of-two block size up to 128. The
    selected node indices refer to the same reduced tree as ``voltage``.
    """
    cell = cuda.blockIdx.x
    lane = cuda.threadIdx.x
    scratch = cuda.shared.array(128, dtype=float64)
    value = 0.0
    for node in range(lane, node_counts[cell], cuda.blockDim.x):
        value += weights[cell, node] * voltage[cell, node]
    scratch[lane] = value
    cuda.syncthreads()
    offset = cuda.blockDim.x // 2
    while offset:
        if lane < offset:
            scratch[lane] += scratch[lane + offset]
        cuda.syncthreads()
        offset //= 2
    if lane == 0:
        signal[sample, cell] = scratch[0] + field_factors[cell] * stimulus
    for index in range(lane, selection_counts[cell], cuda.blockDim.x):
        selected[sample, index, cell] = voltage[cell, selected_nodes[index, cell]]
