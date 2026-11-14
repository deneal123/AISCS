import pytest

from service.infrastructure.execution.gpu_batch_settings import independent_batch_settings


def test_batch_settings_allow_bounded_administrator_tuning():
    defaults = independent_batch_settings({})
    assert defaults['pool_cells'] == defaults['max_cells'] == 20
    assert defaults['require_cell_major'] is False
    assert defaults['reroot'] is False
    assert defaults['cell_major_block_threads'] == 512
    assert defaults['block_cell_segments'] == 40000
    assert defaults['cell_warps'] == 1
    tuned = independent_batch_settings({'GENERATOR_GPU_BATCH_CELLS': '3000',
        'GENERATOR_GPU_POOL_CELLS': '12000', 'GENERATOR_GPU_SEGMENT_BUDGET': '12000000'})
    assert tuned['max_cells'] == 3000
    assert tuned['pool_cells'] == 12000
    assert tuned['segment_budget'] == 12000000
    assert independent_batch_settings({'GENERATOR_GPU_REQUIRE_CELL_MAJOR': '1'})[
        'require_cell_major'] is True
    configured = independent_batch_settings({'GENERATOR_GPU_REROOT': '1',
        'GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS': '128',
        'GENERATOR_GPU_BLOCK_CELL_SEGMENTS': '10000', 'GENERATOR_GPU_CELL_WARPS': '4'})
    assert configured['reroot'] is True
    assert configured['cell_major_block_threads'] == 128
    assert configured['block_cell_segments'] == 10000
    assert configured['cell_warps'] == 4


@pytest.mark.parametrize('env', [
    {'GENERATOR_GPU_BATCH_CELLS': '3001'}, {'GENERATOR_GPU_SEGMENT_BUDGET': '-1'},
    {'GENERATOR_GPU_POOL_CELLS': '19'}, {'GENERATOR_GPU_PREPARE_WORKERS': '1.0'},
    {'GENERATOR_GPU_REQUIRE_CELL_MAJOR': 'true'},
    {'GENERATOR_GPU_REROOT': 'true'}, {'GENERATOR_GPU_CELL_MAJOR_BLOCK_THREADS': '100'},
    {'GENERATOR_GPU_BLOCK_CELL_SEGMENTS': '0'},
    {'GENERATOR_GPU_CELL_WARPS': '3'},
])
def test_invalid_batch_settings_fail_closed(env):
    with pytest.raises(ValueError):
        independent_batch_settings(env)
