"""tool_name в событии — чистое имя, без префикса «Вызываю инструмент».

🔴 Жалоба (трейс-панель): «Вызван инструмент: Вызываю инструмент: search_knowledge_graph»
— двойной префикс. Сериализатор кладёт в `tool_name` либо `metadata["tool_name"]`, либо
`data`; runner'ы писали в `data` уже с префиксом («Вызываю инструмент: X» / «Using tool:
X»), фронт добавлял свой «Вызван инструмент:» — получался дубль. Чистое имя кладём в
metadata, фронт добавляет ровно один префикс.
"""

from __future__ import annotations

from service.events import AgentEvent, EventSerializer, EventType


def _tool_name(event: AgentEvent) -> str:
    return EventSerializer().serialize(event=event, job_id="j").get("tool_name", "")


def test_chat_run_tool_event_has_clean_name():
    ev = AgentEvent(
        type=EventType.TOOL_CALL_START,
        agent_name="general",
        data="Вызываю инструмент: search_knowledge_graph",
        metadata={"tool_name": "search_knowledge_graph"},
    )
    assert _tool_name(ev) == "search_knowledge_graph", (
        "tool_name с префиксом → фронт напечатает «Вызван инструмент: Вызываю инструмент: …»"
    )


def test_metadata_tool_name_wins_over_data():
    """⚠️ ГЛАВНОЕ. Даже если data с префиксом, tool_name берётся из metadata (чистый)."""
    ev = AgentEvent(
        type=EventType.TOOL_CALL_START,
        agent_name="general",
        data="Using tool: analyze_data",
        metadata={"tool_name": "analyze_data"},
    )
    assert _tool_name(ev) == "analyze_data"


def test_runners_pass_clean_tool_name():
    """Оба runner'а кладут чистое имя в metadata — не только data."""
    import inspect

    from service.domain.runners import sdk_run, tool_loop

    for mod in (tool_loop, sdk_run):
        src = inspect.getsource(mod)
        assert '"tool_name"' in src, (
            f"{mod.__name__} не передаёт tool_name в metadata — вернётся двойной префикс"
        )
