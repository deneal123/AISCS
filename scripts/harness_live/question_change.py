"""Модель читает файл до вопроса и повторно после пользовательской правки."""

STEPS = [
    ("ide_read_file", {"path": "hello_world.py"}),
    ("ask_user_question", {"prompt": "Какой файл разобрать подробнее?", "choices": []}),
    ("ide_read_file", {"path": "hello_world.py"}),
    (
        "ide_finish_task",
        {"summary": "Прочитана актуальная пользовательская версия.", "outcome": "unchanged"},
    ),
]


def next_step(completed):
    expected = [name for name, _ in STEPS]
    if completed != expected[: len(completed)] or len(completed) > len(STEPS):
        raise ValueError("acceptance_unexpected_question_history")
    return STEPS[len(completed)] if len(completed) < len(STEPS) else None
