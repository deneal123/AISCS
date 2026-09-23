"""Таймаут синтеза web_search: пользователь получает данные, платформа — счёт.

⚠️ `asyncio.wait_for` отменяет корутину на НАШЕЙ стороне. Провайдер запрос уже принял и
промпт обработал — а промпт здесь самый дорогой во всём агенте: в него уложены ВСЕ
результаты поиска и содержимое прочитанных страниц. `accumulate_usage` стоял строкой
ниже `except` и на этом пути просто не достигался, то есть вызов уходил бесплатным.

Резерв-флор backend'а не спасал: у web_search-запроса есть и роутинг, и раскрытие
follow-up-запроса, они отчитываются — значит `total_tokens > 0`, флор не включается.

## Почему тарифицируется ТОЛЬКО prompt и только оценкой

Объекта ответа не существует — считать нечего, остаётся оценка. А completion
пользователь не получил вовсе: взять за него деньги значило бы взять за то, чего он не
видел. Занижение здесь намеренное и в пользу пользователя.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from service.domain.run_context import require_execution
from service.domain.subagents.web_search import WebSearchAgent
from service.schemas.agents import UserContext


def _ctx(**kwargs) -> UserContext:
    return UserContext(user_id="", request_time=datetime.now(UTC), **kwargs)


BIG_SEARCH_DATA = "## Результаты веб-поиска:\n" + ("подробный фрагмент страницы. " * 400)


@pytest.fixture
def synthesis_times_out(monkeypatch):
    """Синтез не укладывается в бюджет: провайдер молчит дольше таймаута."""
    import service.domain.client as client_mod

    async def _hangs(**kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(client_mod, "create_chat_completion", _hangs)
    monkeypatch.setattr(asyncio, "wait_for", _immediate_timeout)


async def _immediate_timeout(coro, timeout=None):
    """Не ждём 20 секунд ради проверки: закрываем корутину и бросаем таймаут сразу."""
    coro.close()
    raise TimeoutError


@pytest.mark.asyncio
async def test_synthesis_timeout_is_billed(synthesis_times_out):
    """⚠️ Оплаченный промпт доезжает до счёта, а не теряется вместе с ответом."""
    agent = WebSearchAgent({"model": "test-model"})
    execution = require_execution()
    cursor = execution.usage.cursor()

    reply = await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", execution)
    usage = execution.usage.project_since(cursor)

    assert "таймаут" in reply.lower(), "предпосылка: сработала ветка таймаута"
    assert usage.get("prompt", 0) > 0, (
        "синтез с результатами поиска в промпте обработан провайдером и не выставлен в счёт"
    )
    assert usage.get("model") == "test-model", "без модели биллинг уйдёт в дефолт-цену"


@pytest.mark.asyncio
async def test_timeout_does_not_bill_output_the_user_never_saw(synthesis_times_out):
    """Consumption только за промпт: completion пользователю не достался."""
    agent = WebSearchAgent({"model": "test-model"})
    execution = require_execution()
    cursor = execution.usage.cursor()

    await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", execution)
    usage = execution.usage.project_since(cursor)

    assert not usage.get("completion"), "выставлен счёт за вывод, которого пользователь не видел"
    assert usage.get("estimated") is True, "оценка обязана быть помечена как оценка"


@pytest.mark.asyncio
async def test_bigger_prompt_costs_more(synthesis_times_out):
    """Оценка следует за объёмом, а не фиксирована: иначе это не учёт, а константа."""
    agent = WebSearchAgent({"model": "test-model"})

    execution = require_execution()
    cursor = execution.usage.cursor()
    await agent._synthesize("вопрос", _ctx(), "коротко", "test-model", execution)
    small = execution.usage.project_since(cursor)
    cursor = execution.usage.cursor()
    await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", execution)
    big = execution.usage.project_since(cursor)

    assert big["prompt"] > small["prompt"] * 5


# --------------------------------------------------------------------------- #
# Сам дедлайн: он обязан быть ВЫВЕДЕН из таймаутов провайдеров, а не задан числом
# --------------------------------------------------------------------------- #
#
# 🔴 ЖИВАЯ ЖАЛОБА. Запрос «Елизавета Смирнова из МГИМО»: 8 шагов, 52 секунды и
# «Не удалось дождаться итоговой генерации модели (таймаут)» вместо ответа — с сырой
# поисковой выдачей в теле и списанными кредитами. Здесь стояло `wait_for(..., 20)`, при
# том что `routerai_timeout_sec=45`, а у openai дефолт 60. Внешний срок был ЖЁСТЧЕ
# транспортного, то есть на медленном провайдере ответ был невозможен ПО ПОСТРОЕНИЮ:
# отменяли ровно тогда, когда провайдер ещё имел полное право отвечать.
#
# Это тот же класс, что уже ловили у бюджета поиска: два независимых числа разъехались
# (движку давали 15 с при бюджете 16 с, и четыре движка из пяти не запускались никогда).
# Поэтому проверяем не «дедлайн достаточно большой», а СВЯЗЬ: он следует за настройками.


@pytest.fixture
def captured_deadline(monkeypatch):
    """Перехватываем срок, с которым синтез ждёт провайдера."""
    import service.domain.client as client_mod

    seen: dict = {}

    async def _answers(**kwargs):
        class _R:
            choices = [type("C", (), {"message": type("M", (), {"content": "ответ"})()})()]
            usage = None

        return _R()

    async def _capture(coro, timeout=None):
        seen["timeout"] = timeout
        return await coro

    monkeypatch.setattr(client_mod, "create_chat_completion", _answers)
    monkeypatch.setattr(asyncio, "wait_for", _capture)
    return seen


@pytest.mark.asyncio
async def test_deadline_outlives_the_slowest_provider(captured_deadline):
    """⚠️ ГЛАВНОЕ. Дедлайн синтеза СТРОГО больше самого долгого обращения к провайдеру.

    Иначе на этом провайдере пользователь всегда получает «таймаут» и сырую выдачу —
    ровно то, на что пришла жалоба.
    """
    from service.domain.client.registry import max_provider_timeout_sec

    agent = WebSearchAgent({"model": "test-model"})
    await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", {})

    slowest = max_provider_timeout_sec()
    assert captured_deadline["timeout"] > slowest, (
        f"дедлайн синтеза {captured_deadline['timeout']} не переживает самого медленного "
        f"провайдера ({slowest} с): на нём ответ невозможен по построению"
    )


@pytest.mark.asyncio
async def test_deadline_follows_provider_settings(captured_deadline, monkeypatch):
    """⚠️ Дедлайн ВЫВОДИТСЯ, а не совпал случайно с удачной константой.

    Мутация «поставить большое число» проходит проверку выше, но возвращает исходную
    болезнь: следующий провайдер с бо́льшим таймаутом снова окажется срезан. Поэтому
    поднимаем таймаут провайдера и требуем, чтобы дедлайн вырос вместе с ним.
    """
    from service.settings import config

    agent = WebSearchAgent({"model": "test-model"})
    await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", {})
    before = captured_deadline["timeout"]

    monkeypatch.setattr(config.agents, "routerai_timeout_sec", 300.0)
    await agent._synthesize("вопрос", _ctx(), BIG_SEARCH_DATA, "test-model", {})
    after = captured_deadline["timeout"]

    assert after > before, (
        f"дедлайн не следует за настройками провайдеров ({before} → {after}): он задан "
        "числом, и следующий медленный провайдер снова будет срезан"
    )
    assert after > 300.0, f"дедлайн {after} не переживает поднятый таймаут провайдера"
