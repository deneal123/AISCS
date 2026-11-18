"""Administrator-controlled bounds for GPU batching.

Two contexts share one parser but not one default table:

* independent population recording runs one detailed cell batch at a time and
  is cheap to bound, so its defaults stay deliberately small;
* the connected full-population feedback experiment runs the compartmental
  cells WITH network feedback (device-side windowed recording plus synaptic
  events) and at whole-population scale, where the small defaults split the
  population into thousands of padding-dominated batches and leave the
  cell-major kernels idle.
  Those defaults are sized for the whole population on the reference device and
  remain overridable through the same GENERATOR_GPU_* variables.
"""

import os

# name -> (environment variable, minimum, maximum) for the positive integer bounds.
_LIMITS = {
    'segment_budget': ('GENERATOR_GPU_SEGMENT_BUDGET', 1, 12000000),
    'output_budget_bytes': ('GENERATOR_GPU_OUTPUT_BYTES', 1024, 4 * 1024 * 1024 * 1024),
    'workers': ('GENERATOR_GPU_PREPARE_WORKERS', 1, 8),
    'max_cells': ('GENERATOR_GPU_BATCH_CELLS', 1, 3000),
    'pool_cells': ('GENERATOR_GPU_POOL_CELLS', 1, 12000),
    'window_cells': ('GENERATOR_GPU_WINDOW_CELLS', 1, 4096),
    'window_steps': ('GENERATOR_GPU_WINDOW_STEPS', 1, 1000),
    'reduce_workers': ('GENERATOR_GPU_REDUCE_WORKERS', 1, 16),
    'block_cell_segments': ('GENERATOR_GPU_BLOCK_CELL_SEGMENTS', 1, 12000000),
}

# name -> (environment variable, allowed values, default) for the enumerated bounds.
_CHOICES = {
    'require_cell_major': ('GENERATOR_GPU_REQUIRE_CELL_MAJOR', ('0', '1'), False),
    'reroot': ('GENERATOR_GPU_REROOT', ('0', '1'), False),
    'cell_major_block_threads': ('GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS',
                                 ('32', '64', '128', '256', '512'), 512),
    'cell_warps': ('GENERATOR_GPU_CELL_WARPS', ('1', '2', '4', '8'), 1),
}

# Small, deliberately conservative defaults for one independent recording pass.
_INDEPENDENT_DEFAULTS = {
    'segment_budget': 200000,
    'output_budget_bytes': 16 * 1024 * 1024,
    'workers': 1,
    'max_cells': 20,
    'pool_cells': 20,
    'window_cells': 20,
    'window_steps': 25,
    'reduce_workers': 1,
    'block_cell_segments': 40000,
    'require_cell_major': False,
    'reroot': False,
    'cell_major_block_threads': 512,
    'cell_warps': 1,
}

# Whole-population connected feedback: batches are bounded by the padded
# segment budget, the pool drains in wide pools so batching never degenerates
# into many tiny batches, reduction runs on the calling thread, and the
# accelerated cell-major kernel is REQUIRED instead of being silently replaced
# by the generic node-major kernel on the first incompatible batch.
#
# Reduction is single threaded on purpose. A thread pool makes it an order of
# magnitude SLOWER: measured on 2400 real cells the pool cost 0.28 ms/cell at
# one thread, 1.19 ms/cell at two and 2.91 ms/cell at four, reproduced with the
# worker counts alternated over the same cells so warm-up cannot explain it.
# Isolating the compiled structural kernel showed the same collapse (18.4 ->
# 320.2 us/cell from one thread to four), so the pool hurts the numba core
# itself as well as the numpy wrapper around it.
#
# The output budget is deliberately larger than the independent path's because
# the feedback replay records selected compartment voltages on the device in
# addition to the final state, and a cell selects at most one compartment per
# segment. That bounds the true charge at 280 bytes per padded segment (see
# _BYTES_PER_PADDED_SEGMENT), i.e. 840 MB for the 3 000 000-segment budget
# below, which a 256 MiB budget could not hold: the first whole-population run
# failed with "GPU output buffers exceed the supplied budget" at its first
# recorded launch.
_FEEDBACK_DEFAULTS = {
    'segment_budget': 3000000,
    'output_budget_bytes': 1024 * 1024 * 1024,
    # Payload decoding (read, digest, inflate) is pure I/O and scales almost
    # linearly with threads: measured 1.30 s at one thread against 0.38 s at
    # four over 96.9 MB of chunks. It is the one stage that is safe to fan out,
    # because it never touches the numba kernels that a thread pool slows down.
    'workers': 4,
    # Small batches are dominated by fixed per-batch overhead: eight kernel
    # launches with a full device synchronise each, per-cell projection setup and
    # the host callback chain. Measured on the same cells, 800-cell batches ran
    # at 6.8 ms/cell while 3 000-cell batches ran at 5.1 ms/cell, and the real
    # population otherwise splits into 1 300 padding-dominated batches.
    'max_cells': 3000,
    'pool_cells': 12000,
    'window_cells': 1024,
    # A 25-step window synchronises the device eight times per batch and hands
    # the host eight partial traces; 50 halves both without changing the
    # recorded physics, and measured 104.3 -> 81.6 s on the same population
    # slice.
    'window_steps': 50,
    'reduce_workers': 1,
    'block_cell_segments': 40000,
    'require_cell_major': True,
    'reroot': False,
    'cell_major_block_threads': 128,
    'cell_warps': 1,
}

# The cell-major kernels keep four (batch, node) fp64 working columns plus the
# three gate blocks: 8*4 + 8*3 = 56 bytes per padded segment. When recording,
# the fused observation kernel also allocates one fp64 column of the nodal
# weights (8 bytes) plus a (samples, selected, batch) fp64 buffer of the
# selected compartment voltages. A cell selects at most one compartment per
# segment, so that buffer is at most samples * segment_slots * batch * 8, i.e.
# 26 * 8 = 208 bytes per padded segment at the default 25-step window, and the
# whole true charge is bounded by 56 + 8 + 208 = 272 bytes, rounded up here.
# A configuration whose output budget cannot hold its own segment budget fails
# at start-up instead of aborting a long run at its first recorded launch.
_BYTES_PER_PADDED_SEGMENT = 280


# The published names of every bound, in the order a manifest reports them.
SETTING_NAMES = tuple(_LIMITS) + tuple(_CHOICES)


def reported_settings(options):
    """Return the batching bounds that actually reached the solver.

    A manifest states its own batching by reading the values back out of the
    options that were handed to the replay, so a published result cannot claim
    settings that the run did not use. Only bounds that were actually supplied
    are reported; the service child additionally requires the full set.
    """
    if not isinstance(options, dict):
        raise ValueError('Invalid GPU batch settings')
    return {name: options[name] for name in SETTING_NAMES if name in options}


def _settings(env, defaults):
    result = {}
    for name, (key, minimum, maximum) in _LIMITS.items():
        value = env.get(key)
        if value is None:
            result[name] = defaults[name]
            continue
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError(f'Invalid {key}')
        number = int(value)
        if not minimum <= number <= maximum:
            raise ValueError(f'Invalid {key}')
        result[name] = number
    for name, (key, allowed, _fallback) in _CHOICES.items():
        value = env.get(key)
        if value is None:
            result[name] = defaults[name]
            continue
        if value not in allowed:
            raise ValueError(f'Invalid {key}')
        result[name] = int(value) if name in ('cell_major_block_threads', 'cell_warps') else (
            value == '1')
    if result['pool_cells'] < result['max_cells']:
        raise ValueError('GPU pool must hold at least one maximum batch')
    return result


def independent_batch_settings(environment=None):
    """Return conservative defaults or explicitly configured positive integer limits."""
    env = os.environ if environment is None else environment
    return _settings(env, _INDEPENDENT_DEFAULTS)


def full_feedback_batch_settings(environment=None):
    """Return the batching bounds for the connected full-population experiment.

    The defaults keep one padded batch inside the device budget and require the
    accelerated cell-major kernel; every value stays overridable by the same
    administrator variables the independent path uses.
    """
    env = os.environ if environment is None else environment
    result = _settings(env, _FEEDBACK_DEFAULTS)
    capacity = result['output_budget_bytes'] // _BYTES_PER_PADDED_SEGMENT
    if result['segment_budget'] > capacity:
        raise ValueError(
            'GPU segment budget exceeds the output budget: '
            f"segment_budget={result['segment_budget']}, "
            f"output_budget_bytes={result['output_budget_bytes']} holds {capacity}")
    return result