"""Решения модели для повторного чтения; урок меняет первый model-call, не права."""

CONTRACT = {
    "kind": "analysis",
    "criteria": [{"criterion_id": "source", "kind": "read", "target": "hello_world.py"}],
    "needs_clarification": False,
    "question": "",
}
STEPS = [
    ("ide_read_file", {"path": "hello_world.py"}),
    (
        "ide_finish_task",
        {"summary": "Исходник прочитан без изменения и запуска.", "outcome": "unchanged"},
    ),
]


def next_step(completed):
    if completed != [name for name, _ in STEPS[: len(completed)]] or len(completed) > len(STEPS):
        raise ValueError("acceptance_unexpected_tool_history")
    return STEPS[len(completed)] if len(completed) < len(STEPS) else None
