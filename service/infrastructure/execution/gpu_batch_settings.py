"""Administrator-controlled bounds for independent GPU batching."""

import os


def independent_batch_settings(environment=None):
    """Return conservative defaults or explicitly configured positive integer limits."""
    env = os.environ if environment is None else environment
    settings = {
        'segment_budget': ('GENERATOR_GPU_SEGMENT_BUDGET', 200000, 1, 12000000),
        'output_budget_bytes': ('GENERATOR_GPU_OUTPUT_BYTES', 16 * 1024 * 1024,
                                1024, 4 * 1024 * 1024 * 1024),
        'workers': ('GENERATOR_GPU_PREPARE_WORKERS', 1, 1, 8),
        'max_cells': ('GENERATOR_GPU_BATCH_CELLS', 20, 1, 3000),
        'pool_cells': ('GENERATOR_GPU_POOL_CELLS', 20, 1, 12000),
        'window_cells': ('GENERATOR_GPU_WINDOW_CELLS', 20, 1, 4096),
        'window_steps': ('GENERATOR_GPU_WINDOW_STEPS', 25, 1, 1000),
        'reduce_workers': ('GENERATOR_GPU_REDUCE_WORKERS', 1, 1, 16),
        'block_cell_segments': ('GENERATOR_GPU_BLOCK_CELL_SEGMENTS', 40000, 1, 12000000),
    }
    result = {}
    for name, (key, default, minimum, maximum) in settings.items():
        value = env.get(key)
        if value is None:
            result[name] = default
            continue
        if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
            raise ValueError(f'Invalid {key}')
        number = int(value)
        if not minimum <= number <= maximum:
            raise ValueError(f'Invalid {key}')
        result[name] = number
    if result['pool_cells'] < result['max_cells']:
        raise ValueError('GPU pool must hold at least one maximum batch')
    required = env.get('GENERATOR_GPU_REQUIRE_CELL_MAJOR', '0')
    if required not in ('0', '1'):
        raise ValueError('Invalid GENERATOR_GPU_REQUIRE_CELL_MAJOR')
    result['require_cell_major'] = required == '1'
    reroot = env.get('GENERATOR_GPU_REROOT', '0')
    if reroot not in ('0', '1'):
        raise ValueError('Invalid GENERATOR_GPU_REROOT')
    result['reroot'] = reroot == '1'
    threads = env.get('GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS', '512')
    if threads not in ('32', '64', '128', '256', '512'):
        raise ValueError('Invalid GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS')
    result['cell_major_block_threads'] = int(threads)
    warps = env.get('GENERATOR_GPU_CELL_WARPS', '1')
    if warps not in ('1', '2', '4', '8'):
        raise ValueError('Invalid GENERATOR_GPU_CELL_WARPS')
    result['cell_warps'] = int(warps)
    return result
