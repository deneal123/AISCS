"""Обратная связь по доверенным проверкам внутри общего ограниченного цикла."""

from service.shared import deadline

_MARKER = "[harness:verification-repair:"
_REPAIR_TOOLS = frozenset(
    {
        "ide_read_file",
        "ide_list_files",
        "ide_write_file",
        "ide_edit_file",
        "ide_run_command",
        "ask_user_question",
    }
)
INCOMPLETE_MESSAGE = "Задание не завершено: обязательные проверки результата не подтверждены."


def withhold_unverified_text(execution) -> bool:
    state = execution.task_state
    return bool(
        execution.harness is not None
        and state is not None
        and state.contract.kind == "change"
        and isinstance((execution.resources.workspace_ref or {}).get("ide_context"), dict)
    )


def _failed_check(execution):
    state = execution.task_state
    if (
        not withhold_unverified_text(execution)
        or state.cancelled
        or execution.cancelled
        or execution.harness.failure
        or execution.workspace.unconfirmed
        or execution.question.prompt is not None
        or execution.task.stop_reason
        or state.budget.held_credits
        or state.repairs >= state.contract.repair_limit
        or state.rounds >= state.contract.round_limit
        or deadline.must_finalize()
    ):
        return None
    latest = {item.criterion_id: item for item in state.evidence}
    if any(item.outcome == "unknown" for item in latest.values()):
        return None
    return next(
        (
            item
            for item in reversed(tuple(latest.values()))
            if item.kind == "command" and item.outcome == "failed"
        ),
        None,
    )


def record_verification_repair(execution, convo, *, allowed_names) -> bool:
    """Подсказка входит в тот же commit, что и результаты завершённого tool-round."""
    failure = _failed_check(execution)
    if failure is None or not {"ide_read_file", "ide_list_files"}.intersection(allowed_names):
        return False
    marker = f"{_MARKER}{failure.operation_id}]"
    if any(
        message.get("role") == "user" and str(message.get("content", "")).startswith(marker)
        for message in convo
    ):
        return False
    convo.append(
        {
            "role": "user",
            "content": (
                f"{marker}\nПроверка критерия {failure.criterion_id} не пройдена. "
                "Изучи диагностику инструмента и актуальные исходники, исправь причину, затем "
                "повтори ide_run_command для того же criterion_id с сохранённым рецептом и "
                "ожидаемым результатом. Не ослабляй проверку ради успеха. Отчёт ide_finish_task "
                "не заменяет проверку. Если исправление невозможно, укажи конкретный блокер; "
                "не заявляй, что задача выполнена. Не повторяй операцию с неизвестным исходом."
            ),
        }
    )
    return True


def prepare_verification_repair(state, *, restore_only=False) -> bool:
    """Одна подсказка на failed receipt; реальные repairs считает backend при запуске.

    Берём только IDE-инструменты из уже разрешённого policy набора, не из реестра.
    Маркер сохраняется в приватном transcript и не теряется при смене attempt.
    """
    failure = _failed_check(state.execution)
    if failure is None or state.finalizing or state.tool_rounds >= state.max_tool_rounds:
        return False
    marker = f"{_MARKER}{failure.operation_id}]"
    already_recorded = any(
        message.get("role") == "user" and str(message.get("content", "")).startswith(marker)
        for message in state.convo
    )
    if restore_only and not already_recorded:
        # У старого continuation уже может быть оплаченный ответ модели. Нельзя
        # перескочить его replay новым slot только из-за обновления инструкций.
        return False
    eligible = getattr(state.disclosure_controller, "eligible_toolset", None)
    candidates = eligible.tools if eligible is not None else state.openai_tools or []
    tools = [
        tool
        for tool in candidates
        if tool.get("function", {}).get("name") in _REPAIR_TOOLS
        and tool.get("function", {}).get("name") in state.tool_index
    ]
    if not tools:
        return False
    # GigaChat не поддерживает required при нескольких функциях. Адресованное
    # чтение сохраняет одинаковый первый шаг без ослабления до auto.
    names = {tool["function"]["name"] for tool in tools}
    first = next((name for name in ("ide_read_file", "ide_list_files") if name in names), None)
    if first is None:
        return False
    state.openai_tools = tools
    if already_recorded:
        pending_read = state.convo[-1].get("role") == "user" and str(
            state.convo[-1].get("content", "")
        ).startswith(marker)
        state.tool_choice = (
            {"type": "function", "function": {"name": first}} if pending_read else None
        )
        return False
    state.tool_choice = {"type": "function", "function": {"name": first}}
    if state.segment:
        state.convo.append({"role": "assistant", "content": state.segment})
    record_verification_repair(state.execution, state.convo, allowed_names=names)
    state.segment = ""
    state.round_messages = state.convo
    return True
