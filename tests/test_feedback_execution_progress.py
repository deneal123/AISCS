import pytest

from service.infrastructure.execution.process import _valid_progress


@pytest.mark.parametrize(('progress', 'expected'), [
    ({'phase': 'feedback_network', 'iteration': 1, 'done': 0, 'total': 0}, True),
    ({'phase': 'feedback_cells', 'iteration': 2, 'done': 3, 'total': 46}, True),
    ({'phase': 'feedback_cells', 'iteration': True, 'done': 3, 'total': 46}, False),
    ({'phase': 'feedback_cells', 'iteration': 1, 'done': 47, 'total': 46}, False),
    ({'phase': 'feedback_network', 'iteration': 1, 'done': 1, 'total': 1}, False),
    ({'phase': 'cells', 'done': 2, 'total': 46}, True),
    ({'phase': 'cells', 'done': 2, 'total': 46, 'iteration': 1}, False),
])
def test_feedback_progress_is_bounded(progress, expected):
    assert _valid_progress(progress) is expected
