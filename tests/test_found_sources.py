"""Прочитанные ссылки переживают ход диалога.

🔴 Живой кейс: ассистент нашёл вакансию (Tripster, HH.ru), ответил по ней, а на следующий
вопрос «что можешь по ней сказать» ответил, что описания НЕ ВИДИТ, и попросил прислать
ссылку. Результат инструмента — самая дорогая часть хода — исчезал вместе с раундом.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from service.domain.tools import found_sources


def test_outside_a_run_nothing_is_collected() -> None:
    """Вне прогона сбор молчит: инструмент зовут и тесты, и мета-пути."""
    found_sources.remember([{"url": "https://example.test/a", "title": "A"}])

    assert found_sources.collected() == []


def test_same_url_is_remembered_once() -> None:
    """Один источник модель находит несколькими запросами — трижды показанная ссылка
    выглядит как три разных источника."""
    with found_sources.collect():
        found_sources.remember([{"url": "https://a.test/x", "title": "первый"}])
        found_sources.remember([{"url": "https://a.test/x", "title": "он же"}])

        assert len(found_sources.collected()) == 1


def test_collection_is_capped() -> None:
    """Список уезжает и в метаданные, и в промпт следующего хода — потолок обязателен."""
    with found_sources.collect():
        found_sources.remember(
            [
                {"url": f"https://a.test/{i}", "title": "t"}
                for i in range(found_sources.MAX_SOURCES + 7)
            ]
        )

        assert len(found_sources.collected()) == found_sources.MAX_SOURCES


def test_a_parallel_tool_round_still_reaches_the_collector() -> None:
    """🔴 РАУНД ИНСТРУМЕНТОВ ИДЁТ В ДОЧЕРНИХ ЗАДАЧАХ (`asyncio.gather`).

    Они получают КОПИЮ контекста, поэтому присваивание из дочерней задачи наверх не
    вернулось бы. Работает это только потому, что в переменной лежит общий СПИСОК, и
    тест обязан проверять именно параллельный случай: в последовательном сбор прошёл бы
    и при неверной реализации.
    """

    async def scenario() -> int:
        with found_sources.collect():

            async def one(i: int) -> None:
                found_sources.remember([{"url": f"https://a.test/{i}", "title": "t"}])

            await asyncio.gather(*(one(i) for i in range(3)))
            return len(found_sources.collected())

    assert asyncio.run(scenario()) == 3


@pytest.mark.asyncio
async def test_web_search_tool_remembers_what_it_returned(monkeypatch) -> None:
    """⚠️ ТОЧКА ВЫЗОВА: сборщик работает, а инструмент обязан в него ПИСАТЬ.

    Мутация, снимающая одну строку в инструменте, оставила бы тесты выше зелёными.
    """
    from service.domain.tools import web_search_tool

    async def _fake_search(query: str, num_results: int = 5, *, stats=None) -> list[dict]:
        if stats is not None:
            stats["engines_answered"] = 1
        return [{"title": "Вакансия", "url": "https://hh.test/vacancy/1", "snippet": "текст"}]

    monkeypatch.setattr("service.domain.tools.web_search.web_search", _fake_search)

    with found_sources.collect():
        out = await web_search_tool.search_web_tool(
            SimpleNamespace(context={}), json.dumps({"query": "вакансия"})
        )

        assert "hh.test" in out
        assert found_sources.collected() == [
            {"url": "https://hh.test/vacancy/1", "title": "Вакансия", "ok": True}
        ]


@pytest.mark.asyncio
async def test_failed_search_leaves_no_sources(monkeypatch) -> None:
    """Ссылок нет — и приписки о них не будет: пустой список не должен появляться."""
    from service.domain.tools import web_search_tool

    async def _boom(query: str, num_results: int = 5) -> list[dict]:
        raise RuntimeError("поиск лёг")

    monkeypatch.setattr("service.domain.tools.web_search.web_search", _boom)

    with found_sources.collect():
        await web_search_tool.search_web_tool(SimpleNamespace(context={}), '{"query": "x"}')

        assert found_sources.collected() == []
