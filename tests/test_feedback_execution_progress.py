import pytest

from service.infrastructure.execution.process import _population_progress_writer, _valid_progress


def test_independent_population_progress_bounds():
    assert _valid_progress({'phase': 'independent_cells', 'done': 0, 'total': 166700})
    assert _valid_progress({'phase': 'independent_cells', 'done': 166700, 'total': 166700})
    assert not _valid_progress({'phase': 'independent_cells', 'done': 166701, 'total': 166700})
    assert not _valid_progress({'phase': 'independent_cells', 'done': 1, 'total': 166701})
    assert not _valid_progress({'phase': 'independent_cells', 'done': True, 'total': 1})
    assert not _valid_progress({'phase': 'independent_cells', 'done': 1, 'total': 1,
                                'unexpected': True})


def test_population_progress_writer_preserves_last_valid_receipt(tmp_path):
    import json

    import pytest

    report = _population_progress_writer(tmp_path)
    report('independent_cells', 64, 166700)
    path = tmp_path / 'progress.json'
    assert json.loads(path.read_text(encoding='utf8')) == {
        'phase': 'independent_cells', 'done': 64, 'total': 166700}
    with pytest.raises(ValueError):
        report('independent_cells', 166701, 166700)
    assert json.loads(path.read_text(encoding='utf8'))['done'] == 64


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
