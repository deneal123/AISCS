"""Запасные движки поиска реально запускаются.

⚠️ ОНИ НЕ ЗАПУСКАЛИСЬ НИКОГДА, И ЭТО НЕ ПАДАЛО НИГДЕ. Бюджет складывался из двух чисел
в разных файлах: движку давали 15 с (`web_search`), а всему поиску 16 с (`wait_for` у
вызывающих). Когда первый движок тормозит — типичный anti-bot, соединение живо, ответ
не идёт, — он съедал весь бюджет целиком.

Замерено на живом коде до правки: первый движок держал 16.0 с, до bing/brave/yandex
очередь не доходила. Четыре движка из пяти были написаны, покрыты тестами на разбор
выдачи — и не выполнялись ни разу. Наблюдаемое следствие: «поиск ничего не нашёл» там,
где любой из четырёх ответил бы.

Поэтому здесь проверяется не «таймаут равен пяти», а СВОЙСТВО: медленный первый движок
не должен отменять остальные. Оно переживёт любую подкрутку чисел.
"""

from __future__ import annotations

import asyncio

import pytest

from service.domain.tools import web_search as ws


class _Resp:
    def __init__(self, text: str = "<html><body>ничего</body></html>"):
        self.text = text

    def raise_for_status(self):
        return None


def _client_factory(touched: list[str], *, hang_on: str, hang_for: float):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            touched.append(url.split("/")[2])
            if hang_on in url:
                await asyncio.sleep(hang_for)
            return _Resp()

    return _Client


@pytest.mark.asyncio
async def test_slow_first_engine_does_not_starve_the_rest(monkeypatch):
    """Первый движок висит — очередь всё равно доходит до последнего."""
    monkeypatch.setattr(ws, "_search_timeout", lambda: 0.05)
    touched: list[str] = []
    monkeypatch.setattr(
        ws.httpx, "AsyncClient", _client_factory(touched, hang_on="duckduckgo", hang_for=5)
    )

    await asyncio.wait_for(ws.web_search("тест", num_results=4), timeout=ws.search_budget_sec())

    hosts = {h for h in touched}
    assert any("bing" in h for h in hosts), f"до bing очередь не дошла: {sorted(hosts)}"
    assert any("brave" in h for h in hosts), f"до brave очередь не дошла: {sorted(hosts)}"
    assert any("yandex" in h for h in hosts), f"до yandex очередь не дошла: {sorted(hosts)}"


@pytest.mark.asyncio
async def test_budget_covers_every_engine(monkeypatch):
    """⚠️ Внешний бюджет обязан вмещать ВСЮ цепочку, а не один движок.

    Это и есть та самая арифметика, которая разъехалась. Держим её формулой, а не
    двумя константами в разных файлах.
    """
    monkeypatch.setattr(ws, "_search_timeout", lambda: 5.0)

    assert ws.search_budget_sec() > 5.0 * len(ws._ENGINES), (
        "бюджет меньше суммы движков — последние снова станут недостижимы"
    )


@pytest.mark.asyncio
async def test_all_engines_hanging_still_returns_within_budget(monkeypatch):
    """Висят все — возвращаемся пустыми, но в срок, а не по внешнему таймауту.

    Пустая выдача это результат; зависший запрос — нет.
    """
    monkeypatch.setattr(ws, "_search_timeout", lambda: 0.05)
    touched: list[str] = []
    monkeypatch.setattr(
        ws.httpx, "AsyncClient", _client_factory(touched, hang_on="http", hang_for=5)
    )

    results = await asyncio.wait_for(
        ws.web_search("тест", num_results=4), timeout=ws.search_budget_sec()
    )

    assert results == []
    assert len({h for h in touched}) >= len(ws._ENGINES), (
        "не все движки были опробованы, хотя бюджет позволял"
    )


@pytest.mark.asyncio
async def test_fast_first_engine_stops_the_chain(monkeypatch):
    """⚠️ Обратная сторона: нашли на первом — остальных НЕ трогаем.

    Без этого «починку» можно было бы сделать гонкой всех движков сразу, и тесты выше
    остались бы зелёными — а трафик к чужим сервисам вырос бы впятеро на каждом поиске.
    """
    monkeypatch.setattr(ws, "_search_timeout", lambda: 5.0)
    touched: list[str] = []
    found = '<a class="result__a" href="https://example.com/a">Хороший результат</a>'

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            touched.append(url.split("/")[2])
            return _Resp(found)

    monkeypatch.setattr(ws.httpx, "AsyncClient", _Client)

    results = await ws.web_search("тест", num_results=4)

    assert results and results[0]["url"] == "https://example.com/a"
    assert not any("bing" in h or "brave" in h or "yandex" in h for h in touched), (
        f"запасные движки дёрнулись при успешном первом: {touched}"
    )
