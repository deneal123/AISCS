"""LDR deep_research: «стоп» пользователя должен доезжать до LDR.

Регрессия (CRITICAL, деньги): `finally` в `process()` делал только `aclose()` — мы
закрывали свой HTTP-клиент, а исследование на стороне LDR продолжало идти. Токены оно
жжёт через наш же шлюз `/v1`, который НЕ тарифицирует (биллинг берётся из `/metrics`, а
их после отмены мы уже не запрашиваем): провайдер списывает с нас, мы — ни с кого.

⚠️ ПОЧЕМУ ДВОЙНИК ИМЕННО ТАКОЙ. Наивный двойник с БЕСКОНЕЧНЫМ потоком одинаковых
статусов вешает прогон намертво, и обойти это таймаутом нельзя: `_run_ldr` гасит
повторы (`if key == last_key: continue`), поэтому на одинаковых статусах цикл крутится
БЕЗ единой точки передачи управления — событие наверх не уходит, потребитель не
получает ничего, event loop не получает шанса сработать. Отсюда требования: статусы
РАЗНЫЕ (иначе наверх ничего не йилдится) и поток КОНЕЧНЫЙ, но без терминального
статуса — прогон обязан остаться незавершённым, иначе отменять будет нечего.
"""

import asyncio
from types import SimpleNamespace

import pytest

from service.domain import client as client_mod
from service.domain.subagents import deep_research as dr_mod
from service.infrastructure.integration import ldr_research as ldr_mod


class _FakeLDRClient:
    available = True
    model = "ldr-model"

    def __init__(self, *a, **k):
        # Двойник ведёт это состояние как настоящий клиент: по нему слой отмены
        # решает, слать ли `POST /api/terminate`.
        self.active_research_id = None
        self.terminated = []
        self.reports = []

    async def start_research(self, topic):
        self.active_research_id = "rid"
        return "rid"

    async def terminate(self):
        self.terminated.append(self.active_research_id)
        self.active_research_id = None
        return True

    async def iter_status(self, rid):
        # РАЗНЫЕ статусы и КОНЕЧНЫЙ поток — см. преамбулу модуля. Терминального
        # статуса нет: на момент отмены прогон обязан быть незавершённым.
        for pct in (10, 40, 70):
            yield {"progress": pct, "status": "in_progress"}

    async def report(self, rid):
        self.reports.append(rid)
        self.active_research_id = None  # как в настоящем клиенте: отчёт = штатный конец
        return {"summary": "Отчёт по теме исследования на русском.", "sources": []}

    async def metrics(self, rid):
        return {}

    async def aclose(self):
        pass


@pytest.fixture
def ldr_agent(monkeypatch):
    """Агент на двойнике LDR: нативный путь заглушён маркером, guardrails пропускают."""
    fake_holder = {}

    def _factory(*a, **k):
        fake_holder["client"] = _FakeLDRClient(*a, **k)
        return fake_holder["client"]

    monkeypatch.setattr(ldr_mod, "LDRResearchClient", _factory)
    monkeypatch.setattr(dr_mod.DeepResearchAgent, "_resolve_provider", staticmethod(lambda: "ldr"))

    async def _no_models():
        return []

    monkeypatch.setattr(client_mod, "list_available_models", _no_models)

    async def _native_marker(self, *a, **k):
        yield self.error_event("NATIVE_RAN")

    monkeypatch.setattr(dr_mod.DeepResearchAgent, "_run_native", _native_marker)

    agent = dr_mod.DeepResearchAgent(model_settings={})

    async def _safe(_text):
        return {"blocked": False, "sensitive": False, "meta": {}, "message": None}

    monkeypatch.setattr(agent, "evaluate_input_safety", _safe)
    return agent, fake_holder


@pytest.mark.asyncio
async def test_abandoning_stream_terminates_ldr_run(ldr_agent) -> None:
    """Потребитель бросил стрим на середине → `POST /api/terminate` ушёл."""
    agent, holder = ldr_agent
    context = SimpleNamespace(history_messages=[])

    async def _consume_then_abandon():
        gen = agent.process("исследуй тему", context=context)
        async for event in gen:
            # Первый же прогресс-апдейт означает: прогон СТАРТОВАЛ и ещё идёт.
            if (getattr(event, "metadata", None) or {}).get("kind") == "research_progress":
                break
        # Именно так «стоп» выглядит для генератора: потребитель уходит и закрывает
        # его. GeneratorExit прилетает в точку yield и разворачивает наш `finally`.
        await gen.aclose()

    # Страховка от зависания: помогает не при всяком регрессе (см. преамбулу — на
    # одинаковых статусах цикл не отдаёт управление и таймаут не сработает), но
    # дешёвая и снимает часть случаев.
    await asyncio.wait_for(_consume_then_abandon(), timeout=10.0)

    client = holder["client"]
    assert client.terminated == ["rid"]  # отмена доехала до LDR
    assert client.active_research_id is None  # и состояние сброшено
    assert client.reports == []  # отчёт не забирали — прогон был брошен


@pytest.mark.asyncio
async def test_terminate_survives_task_cancellation(ldr_agent) -> None:
    """Отмена ЗАДАЧИ (а не только закрытие генератора) — тоже доезжает до LDR.

    Это и есть боевая форма «стопа»: задачу воркера отменяют, `finally` потребителя
    закрывает генератор, и наш `finally` исполняется в УЖЕ ОТМЕНЁННОЙ задаче. Ради
    этого случая в вызове стоит `asyncio.shield`.
    """
    agent, holder = ldr_agent
    context = SimpleNamespace(history_messages=[])
    started = asyncio.Event()

    async def _drive():
        gen = agent.process("исследуй тему", context=context)
        try:
            async for event in gen:
                if (getattr(event, "metadata", None) or {}).get("kind") == "research_progress":
                    started.set()
                    await asyncio.sleep(3600)  # прогон идёт, ждём отмены извне
        finally:
            await gen.aclose()

    task = asyncio.create_task(_drive())
    await asyncio.wait_for(started.wait(), timeout=10.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    client = holder["client"]
    assert client.terminated == ["rid"]  # отмена доехала, несмотря на CancelledError
    assert client.reports == []


@pytest.mark.asyncio
async def test_terminate_survives_repeated_cancellation(ldr_agent) -> None:
    """Повторная отмена (шатдаун, добивающий задачи) не должна срывать запрос отмены.

    Ради ЭТОГО в вызове стоит `asyncio.shield`, а не ради обычного `task.cancel()`:
    одиночную отмену доставляют один раз, и следующий `await` в `finally` проходит
    нормально (см. `test_terminate_survives_task_cancellation` — он зелёный и без
    shield). А вот отмена, приходящая ПОВТОРНО, бьёт уже по самому `terminate()` —
    без shield запрос не уходит, и это снова деньги.
    """
    agent, holder = ldr_agent
    context = SimpleNamespace(history_messages=[])
    started = asyncio.Event()

    async def _slow_terminate(self=None):
        client = holder["client"]
        await asyncio.sleep(0.05)  # запрос в сети — окно, куда прилетит второй cancel
        client.terminated.append(client.active_research_id)
        client.active_research_id = None
        return True

    async def _drive():
        gen = agent.process("исследуй тему", context=context)
        try:
            async for event in gen:
                if (getattr(event, "metadata", None) or {}).get("kind") == "research_progress":
                    holder["client"].terminate = _slow_terminate
                    started.set()
                    await asyncio.sleep(3600)
        finally:
            await gen.aclose()

    task = asyncio.create_task(_drive())
    await asyncio.wait_for(started.wait(), timeout=10.0)

    # Отменяем настойчиво: так ведёт себя шатдаун, добивающий недожившие задачи.
    for _ in range(5):
        task.cancel()
        await asyncio.sleep(0.01)
    with pytest.raises(asyncio.CancelledError):
        await task

    # shield отвязал запрос от отменённой задачи — даём ему договорить.
    await asyncio.sleep(0.2)
    assert holder["client"].terminated == ["rid"]


@pytest.mark.asyncio
async def test_successful_run_does_not_terminate(ldr_agent) -> None:
    """Штатное завершение → отмену НЕ шлём.

    Половина фикса, которую легко потерять: сброс `active_research_id` в `report()`.
    Без него отмена уходила бы на КАЖДЫЙ успешный ресёрч — лишний запрос и вводящая в
    заблуждение строка в логах про остановку.
    """
    agent, holder = ldr_agent
    context = SimpleNamespace(history_messages=[])

    events = [e async for e in agent.process("исследуй тему", context=context)]
    texts = "".join(str(getattr(e, "data", "") or "") for e in events)

    client = holder["client"]
    assert client.reports == ["rid"]  # прогон дошёл до отчёта
    assert client.terminated == []  # и отменять было нечего
    assert "Отчёт по теме исследования" in texts
    assert "NATIVE_RAN" not in texts
