"""Формат раунда локального исполнителя, не новый цикл или допуск к инструментам."""


def harness_tool_choice(state):
    if state.tool_choice is not None:
        return state.tool_choice
    execution = state.execution
    task = execution.task_state
    if (
        execution.harness is None
        or task is None
        or task.contract.kind != "change"
        or state.provider_session.pinned_provider != "local"
        or not state.openai_tools
        or execution.cancelled
        or task.cancelled
        or execution.harness.failure
        or execution.workspace.ide_unconfirmed
        or execution.question.prompt is not None
        or not isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict)
    ):
        return None
    # Пока проверяемый результат не получен, свободный текст маленькой модели
    # не заменяет действие. Она выбирает один из УЖЕ разрешённых инструментов,
    # включая честный blocked-итог. Все gates, journal и лимиты остаются прежними.
    if execution.completion_verifier.evaluate(task)["unchecked"]:
        if task.rounds == 0 and any(
            tool.get("function", {}).get("name") == "ide_list_files" for tool in state.openai_tools
        ):
            # Первый шаг — наблюдение выбранного дерева, не создание корня.
            # Используем общий сохранённый rounds, поэтому смена attempt не
            # возвращает уже выполненное задание к начальному шагу.
            return {"type": "function", "function": {"name": "ide_list_files"}}
        return "required"
    return None
