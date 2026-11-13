"""Bound padding for experimental heterogeneous GPU batches.

The caller supplies measured per-segment storage, including any time-series
buffers. This planner neither allocates memory nor reserves device capacity.
"""


def plan_batches(segment_counts, *, max_cells, max_padded_segments, max_padding_ratio):
    """Return index batches sorted by size, without losing original identity.

    ``max_padded_segments`` bounds ``batch_size * max(segment_counts)``;
    callers must derive it from the actual device budget and buffer layout.
    ``max_padding_ratio`` bounds padded slots divided by real slots. A single
    oversized cell is rejected instead of being silently truncated.
    """
    if (not isinstance(segment_counts, (list, tuple))
            or any(type(value) is not int or value < 1 for value in segment_counts)
            or type(max_cells) is not int or max_cells < 1
            or type(max_padded_segments) is not int or max_padded_segments < 1
            or isinstance(max_padding_ratio, bool)
            or not isinstance(max_padding_ratio, int | float)
            or not 1 <= max_padding_ratio < float('inf')):
        raise ValueError('Invalid GPU batch limits or segment counts')
    batches = []
    current = []
    real = 0
    for index in sorted(range(len(segment_counts)), key=lambda i: (segment_counts[i], i)):
        size = segment_counts[index]
        if size > max_padded_segments:
            raise ValueError('A morphology exceeds the GPU batch budget')
        padded = size * (len(current) + 1)
        if current and (len(current) >= max_cells or padded > max_padded_segments
                        or padded > max_padding_ratio * (real + size)):
            batches.append(current)
            current = []
            real = 0
        current.append(index)
        real += size
    if current:
        batches.append(current)
    return batches


def estimate_output_bytes(*, max_segments, batch_size, samples, state_trace_cells=3):
    """Return minimum bytes for float64 current and state-trace output buffers.

    This excludes geometry, live gates, events, temporary buffers and CUDA overhead;
    callers must budget those separately. State history is optional; voltage
    and current are retained for every cell. Any
    additional padding in a caller's allocations must also be budgeted.
    """
    values = (max_segments, batch_size, samples)
    if (any(type(value) is not int for value in values)
            or max_segments < 1 or batch_size < 1 or samples < 1
            or type(state_trace_cells) is not int or state_trace_cells < 0):
        raise ValueError('Invalid GPU output buffer dimensions')
    current = samples * max_segments * batch_size * 8
    voltage = samples * max_segments * batch_size * 8
    trace = (samples * max_segments * min(batch_size, state_trace_cells) * 4 * 8
             if state_trace_cells else 4 * 8)
    return {'currents': current, 'voltages': voltage, 'state_trace': trace,
            'total': current + voltage + trace}


def plan_window_batches(segment_counts, *, max_cells, samples, window_steps,
                        output_budget_bytes, max_padding_ratio):
    """Plan similarly sized cells within the solver's window output budget.

    Only voltage/current output buffers are bounded. Geometry, temporary
    arrays and CUDA allocations need a separately enforced memory limit.
    Returned indices refer to the original cell order.
    """
    if (type(samples) is not int or samples < 2 or type(window_steps) is not int
            or window_steps < 1 or type(output_budget_bytes) is not int
            or output_budget_bytes < 1):
        raise ValueError('Invalid window batch limits')
    window_samples = min(samples, window_steps + 1)
    # The solver allocates a four-float dummy state trace in addition to the
    # two float64 output arrays; use the same accounting as its guard.
    max_padded_segments = (output_budget_bytes - 32) // (window_samples * 16)
    if max_padded_segments < 1:
        raise ValueError('GPU output budget too small for a window')
    return plan_batches(segment_counts, max_cells=max_cells,
                        max_padded_segments=max_padded_segments,
                        max_padding_ratio=max_padding_ratio)


def plan_output_batches(segment_counts, *, samples, output_budget_bytes):
    """Partition cells into bounded batches; preserve indexes for restoring input order.

    The budget covers output buffers only, not total device memory. Sorting
    by morphology size reduces padding when a single batch does not fit.
    """
    if (not isinstance(segment_counts, (list, tuple)) or not segment_counts
            or any(type(value) is not int or value < 1 for value in segment_counts)
            or type(samples) is not int or samples < 1
            or type(output_budget_bytes) is not int or output_budget_bytes < 1):
        raise ValueError('Invalid GPU output batch limits')

    def size(indices):
        return estimate_output_bytes(max_segments=max(segment_counts[i] for i in indices),
                                     batch_size=len(indices), samples=samples,
                                     state_trace_cells=0)['total']

    all_indices = list(range(len(segment_counts)))
    if size(all_indices) <= output_budget_bytes:
        return [all_indices]
    batches, current = [], []
    for index in sorted(all_indices, key=lambda i: (segment_counts[i], i)):
        if size([index]) > output_budget_bytes:
            raise ValueError('A morphology exceeds the GPU output budget')
        if current and size([*current, index]) > output_budget_bytes:
            batches.append(current)
            current = []
        current.append(index)
    batches.append(current)
    return batches
