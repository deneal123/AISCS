"""Надбавку берём за ОКАЗАННУЮ услугу, а не за факт вызова.

🔴 ЗАМЕРЕНО НА ЖИВОМ СТЕКЕ. Вопрос про ключевую ставку с включённым поиском:

    логи сайдкара:  TimeoutError в web_search.py — отвалились ВСЕ движки
    мета ответа:    surcharged_tools=["web_search"], surcharge_credits=833
    списано:        1135 кредитов, из них 833 — надбавка за поиск

Поиска не было. Инструмент честно вернул «поиск недоступен, скажи об этом прямо», модель
ответила по памяти — а человек заплатил за услугу, которой не было.

⚠️ СЧЁТ, А НЕ ФЛАГ. Одна надбавка покрывает несколько вызовов (шесть инструментов
песочницы на одно имя; поиск модель зовёт по два-три раза). Правило «был отказ → не берём»
было бы недобиллом: упавший первый вызов отменил бы плату за успешный второй. Здесь это
проверяется отдельно и в обоих порядках.
"""

from __future__ import annotations

import asyncio

import pytest

from service.domain.tools import unbilled_calls


def _meta(tool_name: str, billed: set[str]):
    from service.domain.runners.tool_loop import ToolRoundMixin

    return ToolRoundMixin._billable_tools_meta(tool_name, billed)


def test_a_refused_call_costs_nothing():
    """🔴 ГЛАВНОЕ И ИМЕННО ЗАМЕРЕННЫЙ СЛУЧАЙ: единственный вызов кончился отказом."""
    with unbilled_calls.collect():
        unbilled_calls.waive("web_search_tool")

        assert _meta("search_web", set()) is None, "надбавка за неоказанную услугу"


def test_a_successful_call_is_billed():
    """🔴 ГРАНИЦА. Поиск отработал — платим, иначе правка превратится в бесплатный поиск."""
    with unbilled_calls.collect():
        meta = _meta("search_web", set())

    assert meta and meta["billable_tools"] == ["web_search_tool"]


def test_one_refusal_does_not_cancel_a_successful_call():
    """🔴 НЕДОБИЛЛ, КОТОРЫЙ ЛЕГКО ВВЕСТИ ПРАВКОЙ. Первый вызов упал, второй нашёл — услуга
    оказана, и она платная."""
    with unbilled_calls.collect():
        unbilled_calls.waive("web_search_tool")
        assert _meta("search_web", set()) is None  # первый: отказ

        meta = _meta("search_web", set())  # второй: успех

    assert meta and meta["billable_tools"] == ["web_search_tool"], "успешный вызов стал бесплатным"


def test_every_call_refused_stays_free():
    """⚠️ Три вызова, три отказа — платить не за что."""
    with unbilled_calls.collect():
        for _ in range(3):
            unbilled_calls.waive("web_search_tool")
            assert _meta("search_web", set()) is None


def test_outside_a_run_the_call_is_billed():
    """⚠️ УМОЛЧАНИЕ — ПЛАТНО. Учёт не включён (старый путь, тест, мета-вызов) — берём как
    прежде: молчаливая бесплатность не заметна никому, а деньги теряются каждый ход."""
    assert _meta("search_web", set()) is not None


@pytest.mark.asyncio
async def test_the_ledger_survives_parallel_tool_calls():
    """🔴 РАУНД ИНСТРУМЕНТОВ ИДЁТ ЧЕРЕЗ `asyncio.gather`, а дочерняя задача получает КОПИЮ
    контекста: присваивание из неё наверх НЕ ВЕРНУЛОСЬ БЫ.

    Тест обязан быть параллельным — на последовательном вызове дефект контекста невидим.
    Этот же класс ошибки уже стоил сессии ложного «починено» на сборе ссылок.
    """
    with unbilled_calls.collect():

        async def refusing_tool():
            await asyncio.sleep(0)
            unbilled_calls.waive("web_search_tool")

        await asyncio.gather(*(refusing_tool() for _ in range(2)))

        assert _meta("search_web", set()) is None, "отказ из дочерней задачи не виден наверху"


def test_an_unpriced_tool_is_unaffected():
    """⚠️ Инструмент без надбавки правилом не затронут: у него и цены нет."""
    with unbilled_calls.collect():
        assert _meta("get_current_time", set()) is None


@pytest.mark.parametrize(
    "module_path, marker",
    [
        ("service/domain/tools/web_search_tool.py", "unbilled_calls.waive(BILLING_NAME)"),
        ("service/domain/tools/video_tool.py", "unbilled_calls.waive(BILLING_NAME)"),
        ("service/domain/tools/workspace_tools.py", "unbilled_calls.waive(BILLING_NAME)"),
    ],
)
def test_the_refusing_tools_actually_waive(module_path, marker):
    """🔴 ТОЧКА ВЫЗОВА. Правило верно, но если ни один инструмент не отмечает отказ —
    оно мертво, и надбавка снова берётся за пустоту.

    Разбираем ДЕРЕВО: подстрока нашлась бы и в комментарии, которым правка объяснена.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(module_path).read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "waive"
        and getattr(getattr(node.func, "value", None), "id", "") == "unbilled_calls"
    ]

    assert calls, f"{module_path}: отказ не отмечается — надбавка снова берётся за неуслугу"


def test_the_run_enables_the_ledger():
    """🔴 ВТОРАЯ ТОЧКА ВЫЗОВА. Без включённого учёта `billable()` отвечает «да» всегда, и
    правило выключено целиком — молча."""
    import ast
    import inspect

    from service.application import agent_execution_service as aes

    source = inspect.getsource(aes)
    tree = ast.parse(source)
    enabled = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "collect"
        and getattr(getattr(node.func, "value", None), "id", "") == "unbilled_calls"
    ]

    assert enabled, "учёт отказов не включается на прогоне — надбавка снова слепа"


# --- различение двух пустых ответов ------------------------------------------------------ #


@pytest.mark.asyncio
async def test_no_engine_answered_is_not_billed(monkeypatch):
    """🔴 ИМЕННО ЭТОТ ПУТЬ И СРАБОТАЛ В ЗАМЕРЕ, а первая редакция правки его не покрыла:
    при таймауте ВСЕХ движков `web_search` не бросает исключение, а возвращает пустой
    список — ветка `except` недостижима, и надбавка бралась по-прежнему.

    Живая проверка внутри сайдкара показала это прямо: «ОТКАЗ → надбавка ['web_search_tool']».
    """
    from service.domain.tools import web_search_tool as wst

    async def dead_engines(query, num_results=5, *, stats=None):
        if stats is not None:
            stats["engines_answered"] = 0
        return []

    monkeypatch.setattr("service.domain.tools.web_search.web_search", dead_engines)

    with unbilled_calls.collect():
        text = await wst.search_web_tool(None, '{"query": "ставка"}')

        assert "недоступен" in text, "модели сказали «ничего не найдено» вместо «поиска не было»"
        assert _meta("search_web", set()) is None, "надбавка за неоказанную услугу"


@pytest.mark.asyncio
async def test_engines_answered_but_found_nothing_is_billed(monkeypatch):
    """🔴 ГРАНИЦА. Движки ответили, находок нет — поиск СОСТОЯЛСЯ, и он платный. Слить эти
    два случая в один значит либо снова платить за пустоту, либо раздавать поиск даром."""
    from service.domain.tools import web_search_tool as wst

    async def empty_but_alive(query, num_results=5, *, stats=None):
        if stats is not None:
            stats["engines_answered"] = 2
        return []

    monkeypatch.setattr("service.domain.tools.web_search.web_search", empty_but_alive)

    with unbilled_calls.collect():
        text = await wst.search_web_tool(None, '{"query": "ставка"}')

        assert "ничего не найдено" in text
        assert _meta("search_web", set()) is not None, "состоявшийся поиск стал бесплатным"


@pytest.mark.asyncio
async def test_the_engine_counter_counts_only_answers(monkeypatch):
    """⚠️ Счётчик считает ОТВЕТИВШИХ, а не перебранных: инкремент до `await` сделал бы
    «ни один не ответил» недостижимым, и правило снова стало бы мёртвым."""
    import service.domain.tools.web_search as ws

    async def boom(*a, **kw):
        raise TimeoutError

    monkeypatch.setattr(ws, "_query_engine", boom)

    stats: dict = {}
    results = await ws.web_search("ставка", num_results=3, stats=stats)

    assert results == []
    assert stats["engines_answered"] == 0, "упавший движок засчитан как ответивший"


# --- песочница: недоступность и промах модели — разное ------------------------------------ #


def test_an_unreachable_sandbox_costs_nothing():
    """🔴 Файлы недоступны целиком — услуги не было."""
    from service.domain.integration_failure import IntegrationFailureCode
    from service.domain.tools.workspace_client import WorkspaceUnavailable
    from service.domain.tools.workspace_tools import _failure

    with unbilled_calls.collect():
        outcome = _failure(WorkspaceUnavailable(IntegrationFailureCode.UNAVAILABLE, retryable=True))

        assert outcome.status == "failed"
        assert outcome.failure_code == "unavailable"
        assert outcome.billable is False
        assert _meta("ws_read", set()) is None, "надбавка за недоступную песочницу"


def test_invalid_workspace_call_is_not_billed():
    """S24: failed/invalid/conflict outcomes never reach the charging seam."""
    from service.domain.integration_failure import IntegrationFailureCode
    from service.domain.tools.workspace_client import WorkspaceUnavailable
    from service.domain.tools.workspace_tools import _failure

    with unbilled_calls.collect():
        outcome = _failure(WorkspaceUnavailable(IntegrationFailureCode.INVALID))

        assert outcome.failure_code == "invalid_arguments"
        assert outcome.billable is False
        assert _meta("ws_read", set()) is None
