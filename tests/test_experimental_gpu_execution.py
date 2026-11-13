import pytest

from service.infrastructure.stimulation.experimental_gpu.execution import execute_windows


def test_windows_synchronize_and_check_flags_before_progress():
    events = []
    execute_windows(total_steps=5, window_steps=2,
                    launch=lambda start, end: events.append(('launch', start, end)),
                    synchronize=lambda: events.append(('sync',)),
                    read_flags=lambda: events.append(('flags',)) or [0],
                    cell_ids=[1],
                    progress=lambda end, total: events.append(('progress', end, total)))
    assert events == [
        ('launch', 0, 2), ('sync',), ('flags',), ('progress', 2, 5),
        ('launch', 2, 4), ('sync',), ('flags',), ('progress', 4, 5),
        ('launch', 4, 5), ('sync',), ('flags',), ('progress', 5, 5),
    ]


def test_flagged_window_stops_before_progress_or_next_launch():
    events = []
    with pytest.raises(ValueError, match='cells: 17'):
        execute_windows(total_steps=4, window_steps=2,
                        launch=lambda a, b: events.append((a, b)), synchronize=lambda: None,
                        read_flags=lambda: [1], cell_ids=[17],
                        progress=lambda *_: events.append('progress'))
    assert events == [(0, 2)]


def test_cancellation_prevents_launch():
    def cancel():
        raise RuntimeError('cancelled')

    events = []
    with pytest.raises(RuntimeError, match='cancelled'):
        execute_windows(total_steps=1, window_steps=1,
                        launch=lambda a, b: events.append((a, b)), synchronize=lambda: None,
                        read_flags=lambda: [0], cell_ids=[1], check_cancelled=cancel)
    assert events == []


def test_explicit_table_clamp_still_rejects_nonfinite_voltage():
    options = dict(total_steps=1, window_steps=1, launch=lambda *_: None,
                   synchronize=lambda: None, cell_ids=[1], allow_table_clamp=True)
    execute_windows(**options, read_flags=lambda: [1])
    with pytest.raises(ValueError, match='cells: 1'):
        execute_windows(**options, read_flags=lambda: [2])
