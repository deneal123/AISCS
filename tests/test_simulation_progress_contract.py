import pytest

from service.services.simulations.progress import valid_progress


@pytest.mark.parametrize(('progress', 'expected'), [
    ({'phase': 'feedback_network', 'iteration': 1, 'done': 0, 'total': 0}, True),
    ({'phase': 'feedback_cells', 'iteration': 2, 'done': 3, 'total': 46}, True),
    ({'phase': 'feedback_cells', 'iteration': True, 'done': 3, 'total': 46}, False),
    ({'phase': 'feedback_cells', 'iteration': 1, 'done': 47, 'total': 46}, False),
    ({'phase': 'feedback_network', 'iteration': 1, 'done': 1, 'total': 1}, False),
    ({'phase': 'cells', 'done': 2, 'total': 46}, True),
    ({'phase': 'cells', 'done': 2, 'total': 46, 'iteration': 1}, False),
    ({'phase': 'field', 'done': 0, 'total': 166700}, True),
    ({'phase': 'field', 'done': 1000, 'total': 166700}, True),
    ({'phase': 'field', 'done': 1, 'total': 166701}, False),
    ({'phase': 'field', 'done': True, 'total': 10}, False),
    ({'phase': 'field_verification', 'done': 0, 'total': 0}, True),
    ({'phase': 'field_verification', 'done': 1, 'total': 1}, False),
])
def test_feedback_progress_is_bounded(progress, expected):
    assert valid_progress(progress) is expected
