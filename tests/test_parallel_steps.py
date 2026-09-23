"""Независимые шаги идут ПАРАЛЛЕЛЬНО, а не по одному.

⚠️ ПОЧЕМУ БАРЬЕР, А НЕ ЗАМЕР ВРЕМЕНИ. Тест на «уложились в N секунд» ловит не
параллельность, а скорость машины: зелёный на быстром CI, красный на загруженном — и его
быстро отключают. `asyncio.Barrier(N)` проверяет ровно нужное: все N задач дошли до одной
точки ОДНОВРЕМЕННО.

⚠️ И ПОЧЕМУ НЕДОСТАТОЧНО ПРОСТО ЖДАТЬ БАРЬЕР. Первая версия этих тестов была ФАЛЬШИВОЙ:
мутация «вернуть последовательный цикл» оставляла ЧЕТЫРЕ теста из шести зелёными. Причина
в том, что рабочий код вокруг — fail-open: `except TimeoutError` в поиске и в чтении
страниц проглатывал таймаут барьера и возвращал пустой результат, а итоговое утверждение
всё равно выполнялось («0 результатов» — тоже результат).

Поэтому здесь считается, СКОЛЬКО задач реально прошли барьер, и проверяется это число.
При последовательном исполнении первая задача виснет, до барьера доходит одна, счётчик не
сходится — независимо от того, кто и что проглотил по дороге.
"""

from __future__ import annotations

import asyncio

import pytest

_BARRIER_TIMEOUT = 2.0


def _tiny_budget():
    """Бюджет, при котором все три сжимаемые секции гарантированно не влезают."""
    from service.domain.pipeline.context_budget import ContextBudget

    return ContextBudget(
        window=4000,
        usable=600,
        output_reserve=0,
        prompt_overhead=0,
        sections={"files": 200, "memory": 200, "knowledge": 200},
    )


def _stub_research(monkeypatch, dr, *, search, parse=None):
    """Заглушить внешний мир нативного ресёрча, оставив предметом сам конвейер."""

    async def _default_parse(_url, max_chars=2200):
        return {"content": "содержимое страницы достаточной длины", "title": "t"}

    async def _no_synthesis(**_kw):
        raise RuntimeError("синтез в этом тесте не нужен")

    monkeypatch.setattr(dr, "web_search", search)
    monkeypatch.setattr(dr, "parse_url", parse or _default_parse)
    monkeypatch.setattr(dr, "create_chat_completion", _no_synthesis)


@pytest.mark.asyncio
async def test_compression_map_phase_runs_in_parallel(monkeypatch):
    """Куски одного документа сжимаются одновременно.

    До правки: до 12 полноценных LLM-вызовов подряд, каждый с ретраями и фейловером —
    десятки секунд до первого токена, и это лишь одна секция из трёх сжимаемых.
    """
    from service.domain.pipeline import context_compressor as cc

    monkeypatch.setattr(cc, "get_redis", lambda: None)
    monkeypatch.setattr(cc, "_MAX_CHUNKS", 3)
    monkeypatch.setattr(cc, "_MAP_CONCURRENCY", 3)
    # Иначе весь текст уляжется в ОДИН кусок и барьер на троих не соберётся: тест упал бы
    # «по таймауту», не проверив параллельность.
    monkeypatch.setattr(cc, "_CHUNK_TOKENS", 120)

    barrier = asyncio.Barrier(3)
    passed: list[int] = []

    async def _fake_summarize(_text, _target, _kind, _usage=None, model=""):
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        passed.append(1)
        return "пересказ куска"

    monkeypatch.setattr(cc, "_summarize", _fake_summarize)

    async def _fixed_model():
        return "test-model"

    # Модель резолвится ОДИН раз до map-фазы — иначе тест полез бы за каталогом в сеть.
    monkeypatch.setattr(cc, "_pick_model", _fixed_model)

    raw = "\n\n".join(f"абзац {i} " + "слово " * 400 for i in range(3))
    await cc.compress_to_budget(raw, target=900, kind="memory")

    assert len(passed) == 3, f"до барьера дошло {len(passed)} из 3 — куски сжимались по одному"


@pytest.mark.asyncio
async def test_context_sections_are_fitted_in_parallel(monkeypatch):
    """Секции контекста умещаются одновременно.

    ⚠️ Гоняем НАСТОЯЩИЙ `assemble_context`, а не собственный `gather` в тесте. Первая
    версия делала именно это — проверяла свой же `asyncio.gather` — и потому оставалась
    зелёной при полностью последовательном рабочем коде.
    """
    from service.domain.pipeline import context_assembler as ca
    from service.settings import config

    barrier = asyncio.Barrier(3)
    passed: list[str] = []

    async def _compressor(_raw, _target, kind):
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        passed.append(kind)
        return "сжато"

    async def _fake_budget(**_kw):
        return _tiny_budget()

    monkeypatch.setattr(ca, "compute_budget", _fake_budget)

    big = "очень длинный текст " * 2000
    await ca.assemble_context(
        model_id="m1",
        config=config,
        user_input="вопрос",
        facts="",
        memory=big,
        files=big,
        knowledge=big,
        plan="",
        summary=None,
        history=[],
        compressor=_compressor,
    )

    assert sorted(passed) == ["files", "knowledge", "memory"], (
        f"до барьера дошли только {passed} — секции умещались по одной"
    )


@pytest.mark.asyncio
async def test_research_web_searches_run_in_parallel(monkeypatch):
    """Четыре поисковых запроса независимы: ждём самый медленный, а не сумму.

    До правки — до 64 с только на этом этапе, и всё это до первой строчки отчёта.
    """
    from service.domain.tools import deep_research as dr

    barrier = asyncio.Barrier(4)
    passed: list[str] = []

    async def _fake_search(query, num_results=4):
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        passed.append(query)
        return [{"url": f"https://example.com/{query}", "title": query, "snippet": "s"}]

    _stub_research(monkeypatch, dr, search=_fake_search)

    [c async for c in dr.deep_research("тема", "m1")]

    assert len(passed) == 4, f"до барьера дошло {len(passed)} из 4 — поиски шли по одному"


@pytest.mark.asyncio
async def test_research_page_reads_run_in_parallel(monkeypatch):
    """Найденные страницы читаются одновременно (с ограничением параллелизма)."""
    from service.domain.tools import deep_research as dr

    barrier = asyncio.Barrier(4)
    passed: list[str] = []

    async def _fake_search(query, num_results=4):
        return [{"url": f"https://example.com/{query}", "title": query, "snippet": "s"}]

    async def _fake_parse(url, max_chars=2200):
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        passed.append(url)
        return {"content": "содержимое страницы достаточной длины", "title": "t"}

    _stub_research(monkeypatch, dr, search=_fake_search, parse=_fake_parse)

    [c async for c in dr.deep_research("тема", "m1")]

    assert len(passed) == 4, f"до барьера дошло {len(passed)} из 4 — страницы читались по одной"


@pytest.mark.asyncio
async def test_research_deduplicates_urls_before_fanning_out(monkeypatch):
    """⚠️ Дедупликация ДО веера, а не внутри цикла.

    Один и тот же URL, найденный двумя запросами, иначе читался бы дважды ПАРАЛЛЕЛЬНО —
    вдвое больше сетевой работы ровно там, где мы её сокращаем.
    """
    from service.domain.tools import deep_research as dr

    reads: list[str] = []

    async def _fake_search(_query, num_results=4):
        return [{"url": "https://example.com/one", "title": "t", "snippet": "s"}]

    async def _fake_parse(url, max_chars=2200):
        reads.append(url)
        return {"content": "содержимое страницы достаточной длины", "title": "t"}

    _stub_research(monkeypatch, dr, search=_fake_search, parse=_fake_parse)

    [c async for c in dr.deep_research("тема", "m1")]

    assert reads == ["https://example.com/one"], f"URL прочитан {len(reads)} раз(а)"


@pytest.mark.asyncio
async def test_web_search_agent_reads_pages_in_parallel(monkeypatch):
    """Две страницы веб-поиска читаются одновременно: было 8+8 секунд подряд.

    ⚠️ Патчим МОДУЛЬ-ВЛАДЕЛЕЦ (`domain/tools/web_search`), а не агента: он импортирует
    `parse_url` ВНУТРИ функции, и на самом агенте такого атрибута просто нет.
    """
    import service.domain.client as client_pkg
    from service.domain.subagents.web_search import WebSearchAgent
    from service.domain.tools import web_search as tools_ws

    barrier = asyncio.Barrier(2)
    passed: list[str] = []

    async def _fake_search(_query, num_results=5):
        return [
            {"url": "https://example.com/a", "title": "A", "snippet": "s"},
            {"url": "https://example.com/b", "title": "B", "snippet": "s"},
        ]

    async def _fake_parse(url, max_chars=2000):
        await asyncio.wait_for(barrier.wait(), timeout=_BARRIER_TIMEOUT)
        passed.append(url)
        return {"content": "содержимое страницы", "title": "t", "url": url}

    monkeypatch.setattr(tools_ws, "web_search", _fake_search)
    monkeypatch.setattr(tools_ws, "parse_url", _fake_parse)

    async def _models():
        return ["gpt-4o-mini"]

    async def _no_synthesis(**_kw):
        raise RuntimeError("синтез в этом тесте не нужен")

    monkeypatch.setattr(client_pkg, "list_available_models", _models)
    monkeypatch.setattr(client_pkg, "create_chat_completion", _no_synthesis)

    agent = WebSearchAgent({"model": "gpt-4o-mini"})
    [e async for e in agent.process("запрос", None)]

    assert len(passed) == 2, f"до барьера дошло {len(passed)} из 2 — страницы читались по одной"
