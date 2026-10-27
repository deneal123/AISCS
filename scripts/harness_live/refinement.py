"""Транспортный контраст для приёмки: пропущенный вызов и одна поправка."""

TOOL = "harness_refine_instructions"
INSTRUCTION = "Сначала используй инструменты проекта, затем проверяй фактический результат."


def proposal():
    return TOOL, {"instruction": INSTRUCTION, "tools": []}


def has_guidance(messages):
    return any(INSTRUCTION in str(message.get("content") or "") for message in messages)
