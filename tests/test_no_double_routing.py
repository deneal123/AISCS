"""Один текст роутится ОДИН раз, а не два.

⚠️ Роутинг делался ДВАЖДЫ на каждом сообщении, где инструмент не нужен. Backend зовёт
`/route` (ему нужно решение до диспатча — под резерв кредитов), тот делает LLM-вызов и в
типовом случае отвечает `tool="none"`. `none` не попадал ни в `route_override`, ни во
флаги — и `/run` роутил тот же текст заново.

Второе мнение это не давало. Роутер внутри `/run` видит МЕНЬШЕ: только текст, без
`input_type` и без списка моделей. А на MWS (провайдер по умолчанию) он вызывает ТУ ЖЕ
функцию `route_model` — то есть буквально повторяет первый вызов с меньшим входом.
Набор его категорий — строгое подмножество набора первого роутера, а `none` и `general`
означают там одно и то же.

Цена: полный провайдерский вызов и 300-1500 мс до первого токена. На каждом сообщении.

## Две ловушки, которые ломали очевидное решение

1. **`route_override` для этого НЕ ГОДИТСЯ.** На нём висят гейты: `processor_steps`
   отключает по нему И мульти-интент декомпозицию, И оценку сложности с планом. Положи
   категорию туда — самый частый запрос молча лишился бы планирования, и выглядело бы
   это как ускорение. Поэтому отдельное поле `resolved_category`.

2. **Ручной выбор модели — не дублирование.** Там `route_model` короткозамыкается в
   `source:"manual"` БЕЗ LLM-вызова, `tool` не появляется вовсе, и роутер внутри `/run`
   — единственный. Снимать его нельзя.
"""

from __future__ import annotations

import pytest

from service.domain.pipeline.processor_flow import resolve_agent_route
from service.domain.run_context import RunExecutionContext


class _CountingOrchestrator:
    """Оркестратор, который считает, сколько раз его просили роутить."""

    def __init__(self, answer: str = "general"):
        self.calls = 0
        self._answer = answer

    async def route(self, user_input, thread_id, **kwargs):
        self.calls += 1
        return self._answer


async def _route(orch, **kwargs):
    defaults = {
        "user_input": "как дела",
        "thread_id": "t1",
        "route_override": None,
        "input_type": "text",
        "web_search": False,
        "deep_research": False,
        "execution": RunExecutionContext(),
    }
    return await resolve_agent_route(orchestrator=orch, **{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_ready_category_skips_the_second_llm_call():
    """⚠️ ГЛАВНОЕ: категория уже известна — второго вызова быть не должно."""
    orch = _CountingOrchestrator()

    agent_name, _, complete = await _route(orch, resolved_category="general")

    assert agent_name == "general"
    assert orch.calls == 0, (
        "роутер вызван повторно по тому же тексту — минус полный провайдерский вызов "
        "и 300-1500 мс на каждом сообщении"
    )
    assert complete.metadata.get("agent_type") == "general", "события маршрутизации те же"


@pytest.mark.asyncio
async def test_without_ready_category_we_still_route():
    """⚠️ Ручной выбор модели: авто-роутер не звался, этот вызов ЕДИНСТВЕННЫЙ."""
    orch = _CountingOrchestrator("web_search")

    agent_name, _, _ = await _route(orch, resolved_category=None)

    assert agent_name == "web_search"
    assert orch.calls == 1, "без готовой категории роутинг обязан состояться"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forced",
    [
        {"route_override": "image_gen"},
        {"web_search": True},
        {"deep_research": True},
    ],
    ids=["override", "веб-поиск", "глубокий-поиск"],
)
async def test_explicit_user_choice_wins_over_ready_category(forced):
    """⚠️ Форс пользователя важнее готового ответа роутера.

    Пользователь мог нажать «искать в вебе» уже после того, как авто-роутер решил, что
    инструмент не нужен. Готовая категория не должна его переигрывать.
    """
    orch = _CountingOrchestrator("web_search")

    await _route(orch, resolved_category="general", **forced)

    assert orch.calls == 1, "явное требование пользователя проигнорировано"


# --------------------------------------------------------------------------- #
# Сторона /route: кто вообще кладёт категорию                                   #
# --------------------------------------------------------------------------- #
async def _decide(monkeypatch, routing_meta: dict, **kwargs):
    """Прогнать `/route` с заданным ответом роутер-LLM."""
    import service.domain.tools.router as router_mod
    from service.application.model_routing_service import ModelRoutingService
    from service.domain.run_context import RunExecutionContext

    async def _fake_route_model(*, text, selected_model, input_type, execution=None):
        return "some/model", dict(routing_meta)

    monkeypatch.setattr(router_mod, "route_model", _fake_route_model)

    defaults = {
        "text": "как дела",
        "selected_model": None,
        "input_type": "text",
        "web_search": False,
        "deep_research": False,
        "route_override": None,
        "execution": RunExecutionContext(),
    }
    return await ModelRoutingService().resolve_route(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_tool_none_yields_a_ready_category(monkeypatch):
    """⚠️ ИМЕННО ЗДЕСЬ СНИМАЕТСЯ ВТОРОЙ ВЫЗОВ.

    `none` у этого роутера значит «инструментальный маршрут не требуется» — то же, что
    `general` у роутера внутри `/run`, где другого варианта «без инструмента» нет.
    """
    decision = await _decide(monkeypatch, {"tool": "none", "source": "auto"})

    assert decision.resolved_category == "general", (
        "категория не отдана — `/run` будет роутить тот же текст заново"
    )
    assert decision.route_override is None, (
        "категорию нельзя класть в route_override: на нём висят гейты мульти-интента "
        "и планирования, и они молча отключились бы"
    )


@pytest.mark.asyncio
async def test_manual_model_leaves_category_empty(monkeypatch):
    """⚠️ Ручной выбор модели: авто-роутер НЕ звался, подсказывать нечего.

    `route_model` короткозамыкается в `source:"manual"` без LLM-вызова и без ключа
    `tool`. Роутер внутри `/run` там единственный, а не дублирующий, — снимать его
    было бы потерей маршрутизации, а не экономией.
    """
    decision = await _decide(monkeypatch, {"source": "manual"}, selected_model="some/model")

    assert decision.resolved_category is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "field"),
    [("web_search", "web_search"), ("deep_research", "deep_research")],
)
async def test_tool_routes_still_use_their_own_fields(monkeypatch, tool, field):
    """Инструментальные маршруты едут прежними полями, категорию не занимают."""
    decision = await _decide(monkeypatch, {"tool": tool, "source": "auto"})

    assert getattr(decision, field) is True
    assert decision.resolved_category is None


@pytest.mark.asyncio
async def test_routing_events_are_emitted_either_way():
    """События маршрутизации нужны фронту независимо от того, звали ли модель."""
    orch = _CountingOrchestrator()

    _, start, complete = await _route(orch, resolved_category="general")

    from service.events import EventType

    assert start.type == EventType.ROUTING_START
    assert complete.type == EventType.ROUTING_COMPLETE
