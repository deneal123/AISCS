"""Reject contradictory recipes before creating any durable effect intent."""

import json

from service.domain.runners.tool_runtime import ToolCallOutcome, ToolFailureCode
from service.shared.ide_command import CommandSpec


def command_arguments(raw):
    arguments = json.loads(raw)
    CommandSpec.model_validate(arguments)
    # Preserve original wire arguments: recovery operation IDs must not change
    # merely because a software version starts materializing optional defaults.
    return arguments


def invalid_command():
    return ToolCallOutcome(
        "Неверный рецепт команды. Для python_script/unittest/pytest полностью исключи "
        "поле command: не передавай команду оболочки, пустую строку или строку null. "
        "В target укажи относительный путь. Для shell исключи target и expected_stdout. "
        "Проверка Python также требует expected_stdout и criterion_id=verify_project.",
        "invalid",
        0,
        retryable=True,
        billable=False,
        failure_code=ToolFailureCode.INVALID_ARGUMENTS,
    )
