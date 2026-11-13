"""Experimental deterministic per-cell reduction of electrode contributions."""

from numba import cuda, float64


@cuda.jit
def reduce_window_currents(currents, coefficients, lengths, output):
    """Reduce one cell and one sample per block, without inter-block atomics.

    Inputs are (sample, padded segment, cell), (padded segment, cell), and
    segment counts. Output is (sample, cell) in the same units as the product.
    Launch with exactly 128 threads. This does not validate geometry or model.
    """
    sample = cuda.blockIdx.x
    cell = cuda.blockIdx.y
    lane = cuda.threadIdx.x
    scratch = cuda.shared.array(128, dtype=float64)
    value = 0.0
    for segment in range(lane, lengths[cell], cuda.blockDim.x):
        value += currents[sample, segment, cell] * coefficients[segment, cell]
    scratch[lane] = value
    cuda.syncthreads()
    stride = 64
    while stride:
        if lane < stride:
            scratch[lane] += scratch[lane + stride]
        cuda.syncthreads()
        stride //= 2
    if lane == 0:
        output[sample, cell] = scratch[0]


@cuda.jit
def gather_window_voltages(voltage, indices, counts, output):
    """Gather requested segment voltages without copying all traces to host."""
    selection = cuda.blockIdx.x * cuda.blockDim.x + cuda.threadIdx.x
    sample = cuda.blockIdx.y
    cell = cuda.blockIdx.z
    if selection < counts[cell]:
        output[sample, selection, cell] = voltage[sample, indices[selection, cell], cell]
