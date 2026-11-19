import pytest

from service.infrastructure.execution.gpu_batch_settings import (
    SETTING_NAMES,
    full_feedback_batch_settings,
    independent_batch_settings,
    reported_settings,
)


def test_batch_settings_allow_bounded_administrator_tuning():
    defaults = independent_batch_settings({})
    assert defaults['pool_cells'] == defaults['max_cells'] == 20
    assert defaults['pool_segments'] >= defaults['segment_budget']
    assert defaults['require_cell_major'] is False
    assert defaults['reroot'] is False
    assert defaults['cell_major_block_threads'] == 512
    assert defaults['block_cell_segments'] == 40000
    assert defaults['cell_warps'] == 1
    tuned = independent_batch_settings({'GENERATOR_GPU_BATCH_CELLS': '3000',
        'GENERATOR_GPU_POOL_CELLS': '12000', 'GENERATOR_GPU_SEGMENT_BUDGET': '12000000',
        'GENERATOR_GPU_POOL_SEGMENTS': '12000000'})
    assert tuned['max_cells'] == 3000
    assert tuned['pool_cells'] == 12000
    assert tuned['segment_budget'] == 12000000
    assert tuned['pool_segments'] == 12000000
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
    {'GENERATOR_GPU_CELL_WARPS': '3'}, {'GENERATOR_GPU_POOL_SEGMENTS': '0'},
    # A pool smaller than one batch's segment budget cannot fill a batch.
    {'GENERATOR_GPU_POOL_SEGMENTS': '150000'},
])
def test_invalid_batch_settings_fail_closed(env):
    with pytest.raises(ValueError):
        independent_batch_settings(env)


def test_full_feedback_defaults_are_population_scale_and_required():
    settings = full_feedback_batch_settings({})
    # The connected experiment must not inherit the 20-cell smoke defaults.
    assert settings['max_cells'] >= 500 and settings['pool_cells'] >= settings['max_cells']
    assert settings['segment_budget'] > 200000
    # The recorded feedback pass charges selected compartment voltages on the
    # device, so the budget must hold the whole padded segment budget at the
    # conservative 280 bytes per padded segment.
    assert settings['output_budget_bytes'] == 1024 * 1024 * 1024
    assert (settings['segment_budget'] * 280
            <= settings['output_budget_bytes'])
    assert settings['require_cell_major'] is True
    # A reduce thread pool is an order of magnitude slower than the calling
    # thread (see the note above _FEEDBACK_DEFAULTS), so the population default
    # must stay single threaded.
    assert settings['reduce_workers'] == 1
    assert settings['cell_major_block_threads'] in (32, 64, 128, 256)
    # One warp per block leaves an SM slot running a single warp through every
    # Hines level; four warps per block measured 1.55x on the connected pass.
    assert settings['cell_warps'] == 4
    # A cell-count bound is not a memory bound: the pool drains in ascending
    # width, so 12 000 of the widest cells OOM-killed a whole-population run at
    # 156 399 of 166 700 cells. The segment bound is what actually bounds the
    # resident geometry.
    # 152.7 bytes per segment measured on the widest chunk, so the bound has to
    # stay a memory bound and still hold more than one maximum batch.
    assert settings['segment_budget'] < settings['pool_segments'] < 30000000


def test_full_feedback_settings_stay_administrator_overridable():
    settings = full_feedback_batch_settings({'GENERATOR_GPU_BATCH_CELLS': '300',
        'GENERATOR_GPU_POOL_CELLS': '900', 'GENERATOR_GPU_SEGMENT_BUDGET': '1000000',
        'GENERATOR_GPU_REQUIRE_CELL_MAJOR': '0',
        'GENERATOR_GPU_POOL_SEGMENTS': '5000000'})
    assert settings['max_cells'] == 300 and settings['pool_cells'] == 900
    assert settings['pool_segments'] == 5000000
    assert settings['segment_budget'] == 1000000
    assert settings['require_cell_major'] is False


def test_full_feedback_settings_reject_a_budget_that_cannot_hold_one_batch():
    with pytest.raises(ValueError, match='output budget'):
        full_feedback_batch_settings({'GENERATOR_GPU_OUTPUT_BYTES': '1048576',
                                      'GENERATOR_GPU_SEGMENT_BUDGET': '3000000'})

def test_reported_settings_read_back_only_the_supplied_bounds():
    settings = full_feedback_batch_settings({})
    assert reported_settings(settings) == settings
    assert tuple(reported_settings(settings)) == SETTING_NAMES
    assert reported_settings({'max_cells': 8}) == {'max_cells': 8}
    with pytest.raises(ValueError, match='Invalid GPU batch settings'):
        reported_settings(None)
