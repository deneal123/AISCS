"""Раундов инструментов хватает, чтобы дочитать файлы и ответить.

🔴 НАЙДЕНО ДВУМЯ ЖИВЫМИ ПРОГОНАМИ, поверх 1712 зелёных тестов. Условия: архив `requests`
развёрнут в песочнице, инструменты `ws_*` выданы, вопрос — «покажи код функции
Session.request и объясни построчно». Оба прогона кончились одинаково:

    «Не удалось довести задачу до ответа за отведённое число шагов с инструментами.»

Во второй раз модель успела написать «сейчас я найду и открою код функции» — и ровно на
этой фразе раунды кончились. Пять вызовов LLM с полным промптом, человеку — ничего.

Четыре раунда верны для обычного чата: инструмент зовут один раз, а каждый раунд
переотправляет весь растущий диалог. Но минимальная цепочка чтения кода — посмотреть
дерево, найти место, прочитать файл — это УЖЕ три, и на ответ остаётся один: ЛЮБАЯ
неудачная проба роняет прогон. Поэтому лимит поднимается только там, где идёт работа с
файлами, и обычный чат остаётся в прежней цене.
"""

from __future__ import annotations

from types import SimpleNamespace

from service.domain.runners.chat_run import (
    FILE_WORK_TOOL_ROUNDS,
    _compact_system_after_workspace_tool,
    _tool_rounds_for,
    _with_workspace_tool_protocol,
)


def _tool(name: str) -> dict:
    """Инструмент в ТОЙ ЖЕ форме, в какой он лежит в наборе прогона.

    🔴 ЗДЕСЬ БЫЛ `SimpleNamespace(name=…)` — форма, которую я ПРЕДПОЛОЖИЛ. Настоящий набор
    уже сериализован в OpenAI-формат (`_resolve_toolset` → `_tools_to_openai`), то есть это
    СЛОВАРИ `{"type": "function", "function": {"name": …}}`. Из-за этого правило про раунды
    не срабатывало НИ РАЗУ, а тест был зелёным: он проверял мою догадку, а не код.

    Нашёл человек, не тест: на GigaChat агент прочитал файлы четырьмя вызовами и получил
    «не удалось довести задачу до ответа за отведённое число шагов» — 5804 кредита за ничего.
    """
    return {"type": "function", "function": {"name": name, "description": "", "parameters": {}}}


def _legacy_tool(name: str):
    """Объект с `.name` — прямые вызовы в обход сериализации. Тоже обязан распознаваться."""
    return SimpleNamespace(name=name)


def test_file_work_gets_more_rounds_than_ordinary_chat():
    """🔴 ГЛАВНОЕ. `ws_list` → `ws_grep` → `ws_read` → ответ не влезают в четыре раунда."""
    rounds = _tool_rounds_for(4, [_tool("ws_list"), _tool("ws_read"), _tool("fetch_url")])

    assert rounds == FILE_WORK_TOOL_ROUNDS
    assert rounds >= 6, (
        "на чтение дерева, поиск, чтение файла и ответ раундов снова не хватит — человек "
        "получит «не удалось довести задачу до ответа»"
    )


def test_ordinary_chat_keeps_its_price():
    """🔴 ГРАНИЦА. Раунд переотправляет ВЕСЬ растущий диалог: поднять лимит всем значило бы
    платить за файловую работу в каждом запросе, где её нет."""
    assert _tool_rounds_for(4, [_tool("fetch_url"), _tool("search_web")]) == 4
    assert _tool_rounds_for(4, []) == 4
    assert _tool_rounds_for(4, None) == 4


def test_a_declared_higher_limit_is_never_lowered():
    """⚠️ Агент, которому раундов нужно больше, не должен их ПОТЕРЯТЬ из-за этого правила."""
    assert _tool_rounds_for(12, [_tool("ws_read")]) == 12


def test_the_serialized_shape_is_what_actually_arrives():
    """🔴 ГЛАВНОЕ ПОСЛЕ ЖИВОГО ОТЧЁТА. Набор приходит СЛОВАРЯМИ, и правило обязано читать
    имя оттуда. Форма взята из кода (`_tools_to_openai`), а не придумана."""
    from service.domain.base import _tools_to_openai
    from service.domain.tools.workspace_tools import WORKSPACE_TOOLS

    real = _tools_to_openai(list(WORKSPACE_TOOLS))

    assert isinstance(real[0], dict), "форма набора изменилась — правило снова может ослепнуть"
    assert _tool_rounds_for(4, real) == FILE_WORK_TOOL_ROUNDS, (
        "на НАСТОЯЩЕМ наборе лимит не поднялся — ровно этот дефект и дал человеку "
        "«не удалось довести задачу до ответа»"
    )


def test_both_shapes_are_understood():
    """⚠️ Словарь — боевой путь, объект с `.name` — прямые вызовы. Требовать один значило бы
    снова угадывать, какой придёт."""
    assert _tool_rounds_for(4, [_legacy_tool("ws_read")]) == FILE_WORK_TOOL_ROUNDS
    assert _tool_rounds_for(4, [_tool("ws_read")]) == FILE_WORK_TOOL_ROUNDS


def test_a_malformed_entry_does_not_crash_the_rule():
    """⚠️ Набор собирает не этот модуль: неожидаемая запись не должна ронять прогон целиком."""
    assert _tool_rounds_for(4, [None, {}, {"function": None}, "строка"]) == 4


def test_workspace_protocol_is_added_only_when_capability_is_actually_offered():
    original = [{"role": "system", "content": "base"}, {"role": "user", "content": "task"}]

    prepared = _with_workspace_tool_protocol(original, [_tool("ws_write")])

    assert prepared is not original
    assert original[0]["content"] == "base"
    assert "сначала обязательно" in prepared[0]["content"]
    assert "ws_*" in prepared[0]["content"]


def test_non_workspace_tools_do_not_change_prompt_or_cost():
    messages = [{"role": "system", "content": "base"}, {"role": "user", "content": "task"}]

    assert _with_workspace_tool_protocol(messages, [_tool("fetch_url")]) is messages
    assert _with_workspace_tool_protocol(messages, []) is messages


def test_repo_map_is_removed_from_followup_tool_rounds():
    """Карта архива нужна для первого ws-вызова, а не для каждого следующего prompt."""
    context = SimpleNamespace(system_context="# Graph Report\nGod Nodes\n" + "x" * 20_000)
    initial = "Базовая инструкция\n\n" + context.system_context

    compacted = _compact_system_after_workspace_tool(initial, context)

    assert "God Nodes" not in compacted
    assert "Карта репозитория уже использована" in compacted
    assert len(compacted) < len(initial) // 10


def test_the_rule_looks_at_names_not_at_count():
    """⚠️ Признак — именно файловые инструменты, а не «много инструментов»: набор из десяти
    web-инструментов файловой работой не является и лишних шагов не заслуживает."""
    many_web = [_tool(f"web_{i}") for i in range(10)]

    assert _tool_rounds_for(4, many_web) == 4


def test_the_limit_is_applied_where_the_toolset_is_known():
    """🔴 ТОЧКА ВЫЗОВА. Правило верное, а в цикле остался прежний `_as_int` — и всё как было.
    Этот класс переживал мои мутации трижды, поэтому проверяется деревом отдельно.
    """
    import ast
    import inspect

    from service.domain.runners import chat_run

    tree = ast.parse(inspect.getsource(chat_run))
    assigns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "max_tool_rounds" for t in node.targets)
    ]

    assert assigns, "лимит раундов больше нигде не назначается — тест устарел, а не правило"
    assert all(
        isinstance(a.value, ast.Call) and getattr(a.value.func, "id", "") == "_tool_rounds_for"
        for a in assigns
    ), "лимит снова берётся напрямую, минуя правило про файловую работу"
