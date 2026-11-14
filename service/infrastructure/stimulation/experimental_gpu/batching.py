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


def plan_cell_major_window_batches(node_counts, segment_counts, selection_counts, *, max_cells,
                                   samples, window_steps, output_budget_bytes, max_padding_ratio,
                                   generic_fallback=False):
    """Plan batches using the reduced cell-major state and observation buffers.

    The bound matches the solver's output-budget guard, not total GPU memory:
    geometry, events, CUDA allocations and host storage remain outside it.
    Selection counts must be checked again against the actual group factory.
    """
    if (not isinstance(node_counts, (list, tuple))
            or not isinstance(segment_counts, (list, tuple))
            or not isinstance(selection_counts, (list, tuple))
            or not node_counts or len(node_counts) != len(segment_counts)
            or len(node_counts) != len(selection_counts)
            or any(type(n) is not int or n < 1 for n in node_counts)
            or any(type(s) is not int or s < 1 for s in segment_counts)
            or any(type(k) is not int or k < 0 for k in selection_counts)
            or any(s > n or k > s for n, s, k in
                   zip(node_counts, segment_counts, selection_counts, strict=True))
            or type(generic_fallback) is not bool
            or type(max_cells) is not int or max_cells < 1
            or type(samples) is not int or samples < 2
            or type(window_steps) is not int or window_steps < 1
            or type(output_budget_bytes) is not int or output_budget_bytes < 1
            or isinstance(max_padding_ratio, bool)
            or not isinstance(max_padding_ratio, int | float)
            or not 1 <= max_padding_ratio < float('inf')):
        raise ValueError('Invalid cell-major window batch limits')

    window_samples = min(samples, window_steps + 1)

    def required_bytes(batch, n, s, k):
        reduced = batch * (40 * n + 24 * s + 8 * k + 16 + window_samples * (k + 1) * 8)
        if generic_fallback:
            generic = 16 * s * batch * window_samples + 32
            generic += window_samples * batch * (k + 1) * 8
            return max(reduced, generic)
        return reduced

    groups, current = [], []
    max_nodes = max_segments = max_selected = real_segments = 0
    for index in sorted(range(len(node_counts)),
                        key=lambda i: (segment_counts[i], node_counts[i], i)):
        n = max(max_nodes, node_counts[index])
        s = max(max_segments, segment_counts[index])
        k = max(max_selected, selection_counts[index], 1)
        batch = len(current) + 1
        required = required_bytes(batch, n, s, k)
        padded = s * batch
        real = real_segments + segment_counts[index]
        if current and (batch > max_cells or required > output_budget_bytes
                        or padded > max_padding_ratio * real):
            groups.append(current)
            current, real_segments = [], 0
            n, s = node_counts[index], segment_counts[index]
            k, batch = max(1, selection_counts[index]), 1
            required = required_bytes(batch, n, s, k)
        if required > output_budget_bytes:
            raise ValueError('A morphology exceeds the GPU output budget')
        current.append(index)
        max_nodes, max_segments, max_selected = n, s, k
        real_segments += segment_counts[index]
    if current:
        groups.append(current)
    return groups


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
    batches, current, current_max = [], [], 0
    for index in sorted(all_indices, key=lambda i: (segment_counts[i], i)):
        if size([index]) > output_budget_bytes:
            raise ValueError('A morphology exceeds the GPU output budget')
        proposed_max = max(current_max, segment_counts[index])
        proposed = estimate_output_bytes(max_segments=proposed_max,
            batch_size=len(current) + 1, samples=samples, state_trace_cells=0)['total']
        if current and proposed > output_budget_bytes:
            batches.append(current)
            current = []
            proposed_max = segment_counts[index]
        current.append(index)
        current_max = proposed_max
    batches.append(current)
    return batches
