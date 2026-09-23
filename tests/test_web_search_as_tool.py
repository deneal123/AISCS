"""Веб-поиск как ИНСТРУМЕНТ обычного ответа: гейт и тарификация.

🔴 ДЫРА В ВЫРУЧКЕ, КОТОРУЮ ЗАКРЫВАЮТ ЭТИ ТЕСТЫ. Надбавка берётся по МАРШРУТУ
(`metadata["agent_type"]`), а инструмент внутри `general` маршрута не меняет: снаружи
прогон выглядит как обычный ответ. Без отдельного сигнала поиск был бы бесплатным, и
заметить это по поведению нельзя — ошибок нет, счёт просто меньше.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service.domain.runners import tool_loop as chat_run
from service.domain.subagents.general import GeneralAgent
from service.schemas.agents import UserContext


def _ctx(**kw) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kw)


def _names(agent, context) -> set[str]:
    return {getattr(t, "name", "") for t in agent._applicable_tools(context)}


# --------------------------------------------------------------------------- #
# Гейт: инструмент существует, только когда он нужен                           #
# --------------------------------------------------------------------------- #
def test_web_tool_is_absent_by_default():
    """🔴 Схема стоит токенов в КАЖДОМ запросе, включая «привет»."""
    assert "search_web" not in _names(GeneralAgent({"model": "m"}), _ctx())


def test_web_tool_appears_when_the_orchestrator_asked():
    assert "search_web" in _names(GeneralAgent({"model": "m"}), _ctx(web_tool_enabled=True))


def test_web_tool_gate_does_not_leak_to_neighbours():
    """Гейт срабатывает по СВОЕМУ признаку, а не включает всё разом."""
    names = _names(GeneralAgent({"model": "m"}), _ctx(web_tool_enabled=True))

    assert "analyze_data" not in names and "search_knowledge_graph" not in names


def test_gate_costs_tokens_only_when_enabled():
    """Экономия должна быть ИЗМЕРИМА — иначе гейт бессмысленен."""
    agent = GeneralAgent({"model": "m"})

    assert agent.fixed_prompt_tokens(_ctx()) < agent.fixed_prompt_tokens(
        _ctx(web_tool_enabled=True)
    )


# --------------------------------------------------------------------------- #
# Тарификация                                                                  #
# --------------------------------------------------------------------------- #
def test_search_is_marked_for_billing():
    """Имя для счёта ОТДЕЛЬНОЕ от маршрутного `web_search`."""
    meta = GeneralAgent({"model": "m"})._billable_tools_meta("search_web", set())

    assert meta["billable_tools"] == ["web_search_tool"]
    assert meta["tool_name"] == "search_web"


def test_free_tools_are_not_marked():
    """`fetch_url` и соседи бесплатны — метка на них означала бы приписку к счёту."""
    agent = GeneralAgent({"model": "m"})

    assert agent._billable_tools_meta("fetch_url", set()) is None
    assert agent._billable_tools_meta("analyze_data", set()) is None


def test_repeated_search_is_billed_once():
    """🔴 Два вызова → РОВНО один элемент: ни потери, ни задвоения.

    Метка кумулятивна, потому что потребитель складывает метаданные событий ПЕРЕЗАПИСЬЮ:
    одиночное значение затёрлось бы вторым вызовом и отменило учёт первого. А повтор в
    списке дал бы двойную плату за один и тот же вопрос.
    """
    agent = GeneralAgent({"model": "m"})

    billed: set[str] = set()
    agent._billable_tools_meta("search_web", billed)
    second = agent._billable_tools_meta("search_web", billed)

    assert second["billable_tools"] == ["web_search_tool"]


def test_two_different_tools_both_reach_the_bill(monkeypatch):
    """🔴 НАКОПЛЕНИЕ, А НЕ ПОСЛЕДНЕЕ ЗНАЧЕНИЕ.

    ⚠️ Проверяется с ДВУМЯ платными именами, потому что с одним свойство ненаблюдаемо:
    мутация «возвращать только текущий инструмент» проходила мимо теста про повтор —
    там оба вызова дают один и тот же элемент. Платный инструмент сегодня один, но
    потребитель складывает метаданные ПЕРЕЗАПИСЬЮ, и в день появления второго потеря
    была бы молчаливой: счёт просто меньше, ошибок нет.
    """
    agent = GeneralAgent({"model": "m"})
    monkeypatch.setattr(
        chat_run,
        "tool_billing_names",
        lambda: {"search_web": "web_search_tool", "analyze_data": "analyze_data_tool"},
    )

    billed: set[str] = set()
    agent._billable_tools_meta("search_web", billed)
    last = agent._billable_tools_meta("analyze_data", billed)

    assert last["billable_tools"] == ["analyze_data_tool", "web_search_tool"], (
        "последнее событие не несёт полный набор — при перезаписи первый инструмент пропадёт"
    )


def test_billing_name_is_declared_in_the_contract():
    """Имя обязано быть в контракте: иначе потребитель отфильтрует его как неизвестное."""
    from service.contracts import BILLABLE_TOOLS

    assert "web_search_tool" in BILLABLE_TOOLS
    assert "web_search" in BILLABLE_TOOLS, "маршрутная надбавка не должна пропасть"


# --------------------------------------------------------------------------- #
# Сам инструмент                                                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_results_are_compact(monkeypatch):
    """Результат уходит в диалог и переотправляется КАЖДЫМ раундом — тел страниц не шлём."""
    from service.domain.tools import web_search_tool as mod

    async def _search(query, num_results=5, *, stats=None):
        if stats is not None:
            stats["engines_answered"] = 1
        return [
            {"title": "Курс", "url": "https://x/1", "snippet": "ф" * 5000},
            {"title": "Ещё", "url": "https://x/2", "snippet": "коротко"},
        ]

    monkeypatch.setattr("service.domain.tools.web_search.web_search", _search)

    out = await mod.search_web_tool(None, '{"query": "курс биткоина"}')

    assert "https://x/1" in out and "Курс" in out
    assert len(out) < 1500, "в диалог уехало тело страницы, а не выдержка"


@pytest.mark.asyncio
async def test_empty_results_say_so_explicitly(monkeypatch):
    """🔴 Пустая строка читалась бы моделью как «нашлось» → выдуманные цифры со ссылкой."""
    from service.domain.tools import web_search_tool as mod

    async def _search(query, num_results=5, *, stats=None):
        if stats is not None:
            stats["engines_answered"] = 1
        return []

    monkeypatch.setattr("service.domain.tools.web_search.web_search", _search)

    out = await mod.search_web_tool(None, '{"query": "чепуха"}')

    assert "не найдено" in out and "не выдумывай" in out


@pytest.mark.asyncio
async def test_search_failure_is_reported_not_swallowed(monkeypatch):
    from service.domain.tools import web_search_tool as mod

    async def _search(query, num_results=5, *, stats=None):
        if stats is not None:
            stats["engines_answered"] = 1
        raise RuntimeError("движки легли")

    monkeypatch.setattr("service.domain.tools.web_search.web_search", _search)

    out = await mod.search_web_tool(None, '{"query": "курс"}')

    assert "недоступен" in out
