import pytest

from service.services.simulations.progress import valid_progress


def test_full_feedback_progress_is_bounded_and_identifies_iteration():
    assert valid_progress({'phase': 'full_active', 'done': 0, 'total': 166700})
    assert valid_progress({'phase': 'full_control', 'done': 12, 'total': 166700})
    assert valid_progress({'phase': 'full_feedback', 'iteration': 2, 'done': 12, 'total': 166700})
    assert not valid_progress({'phase': 'full_feedback', 'done': 12, 'total': 166700})
    assert not valid_progress({'phase': 'full_active', 'done': 166701, 'total': 166700})


def test_independent_population_progress_is_bounded():
    assert valid_progress({'phase': 'independent_cells', 'done': 0, 'total': 166700})
    assert valid_progress({'phase': 'independent_cells', 'done': 166700, 'total': 166700})
    assert not valid_progress({'phase': 'independent_cells', 'done': 166701, 'total': 166700})
    assert not valid_progress({'phase': 'independent_cells', 'done': True, 'total': 166700})


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
    ({'phase': 'network', 'done': 0, 'total': 0}, True),
    ({'phase': 'network', 'done': 0, 'total': 1000}, True),
    ({'phase': 'network', 'done': 25, 'total': 100}, True),
    ({'phase': 'network', 'done': 101, 'total': 100}, False),
    ({'phase': 'network', 'done': 1, 'total': 1001}, False),
])
def test_feedback_progress_is_bounded(progress, expected):
    assert valid_progress(progress) is expected
