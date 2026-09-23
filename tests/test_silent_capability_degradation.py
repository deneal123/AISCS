"""Каталог недоступен — деградация СЛЫШНА, а не выглядит штатной работой.

⚠️ Каталог OpenRouter — ЕДИНСТВЕННЫЙ источник и для «умеет ли модель инструменты», и для
окна модели. Один тихий отказ давал сразу две деградации, и обе снаружи неотличимы от
нормы:

* инструменты снимаются со всех моделей вне allowlist — пользователь получает уверенный
  ответ по памяти модели и фразу «у меня нет доступа к интернету» вместо веб-поиска,
  анализа данных и базы знаний;
* окно модели считается дефолтным (32k) — компрессор запускается там, где не нужен, до
  39 провайдерских вызовов на пустом месте.

Оба отказа логировались на DEBUG. На типовом INFO это означает: НИ ОДНОЙ записи. Кэш при
этом процессный и пустой при старте, поэтому постоянно падающий запрос делает состояние
«деградировали» не эпизодом, а нормой на весь аптайм.

## Почему проверки смотрят на ПРИЧИНУ ОТКАЗА, а не на возвращаемое значение

Возвращаемое значение при этой деградации правдоподобное: пустой список инструментов —
законный ответ для модели, которая их не умеет. Одним им «модель не умеет» и «мы не смогли
выяснить» неразличимы, а действий требуют разных.

⚠️ Раньше единственным следом был ЛОГ, и проверки смотрели на него. Теперь причина —
типизированная часть ответа (`ToolSet.omissions`) и уезжает событием в трейс, поэтому
проверяется она, а лог остаётся для оператора.

⚠️ Гипотеза о ПРИЧИНЕ (проверяется в проде, не здесь): `_fetch_openrouter` ходит голым
httpx-клиентом, тогда как `AGENTS__PROXY_PROVIDERS=openrouter,openai` во ВСЕХ контурах
объявляет openrouter доступным только через прокси, и провайдерские клиенты его строят.
Стандартных `HTTPS_PROXY`/`ALL_PROXY` в окружении нет, значит `trust_env` httpx ничего не
подхватит. Эти тесты не доказывают, что запрос падает, — они гарантируют, что если он
падает, мы об этом узнаем.
"""

from __future__ import annotations

import logging

import pytest

from service.domain.subagents.general import GeneralAgent


@pytest.mark.asyncio
async def test_unknown_capability_is_not_silent(monkeypatch, caplog):
    """⚠️ «Не смогли выяснить» обязано отличаться от «модель не умеет»."""
    import service.shared.model_catalog as catalog_mod

    async def _boom(model):
        raise ConnectionError("каталог недоступен")

    monkeypatch.setattr(catalog_mod, "model_supports_tools", _boom)

    agent = GeneralAgent({"model": "test-model"})
    agent.tools = [object()]  # инструменты у агента ЕСТЬ — значит их отняли

    with caplog.at_level(logging.WARNING):
        toolset = await agent._resolve_toolset("test-model")

    assert toolset.tools == [], "поведение прежнее: без каталога идём без инструментов"
    assert [o.reason for o in toolset.omissions] == ["catalog_unknown"], (
        "причина отказа неотличима от «модель не умеет» — пользователь получит уверенный "
        "ответ по памяти модели, и связать это с недоступным каталогом будет нечем"
    )
    assert any(
        "tool capability catalog failed code=unavailable" in r.message for r in caplog.records
    )


@pytest.mark.asyncio
async def test_model_without_tool_support_stays_quiet(monkeypatch, caplog):
    """⚠️ Штатный случай молчит: иначе предупреждение станет фоновым шумом.

    Модель, которая инструментов не умеет, — это не сбой, и таких моделей много.
    """
    import service.shared.model_catalog as catalog_mod

    async def _no_tools(model):
        return False

    monkeypatch.setattr(catalog_mod, "model_supports_tools", _no_tools)

    agent = GeneralAgent({"model": "test-model"})
    agent.tools = [object()]

    with caplog.at_level(logging.WARNING):
        toolset = await agent._resolve_toolset("test-model")

    assert toolset.tools == []
    assert [o.reason for o in toolset.omissions] == ["model_no_tool_support"], (
        "штатный случай обязан называться своим именем, иначе он неотличим от сбоя каталога"
    )
    assert not caplog.records, "штатный случай не должен шуметь на WARNING"


@pytest.mark.asyncio
async def test_catalog_failure_is_logged_with_consequences(monkeypatch, caplog):
    """Сам каталог тоже перестал молчать: отказ виден на WARNING."""
    import service.shared.model_catalog as catalog_mod

    async def _boom():
        raise ConnectionError("openrouter недоступен")

    monkeypatch.setattr(catalog_mod, "_fetch_openrouter", _boom)
    monkeypatch.setattr(catalog_mod, "_cache", {"ts": 0.0, "data": {}})

    with caplog.at_level(logging.WARNING):
        assert await catalog_mod.get_openrouter_catalog() == {}

    assert any("OpenRouter" in r.message for r in caplog.records), (
        "каталог отвалился беззвучно — а от него зависят и инструменты, и окно модели"
    )


@pytest.mark.asyncio
async def test_warm_cache_does_not_warn(monkeypatch, caplog):
    """Тёплый кэш — не повод шуметь: сети не касаемся вовсе."""
    import time

    import service.shared.model_catalog as catalog_mod

    monkeypatch.setattr(
        catalog_mod, "_cache", {"ts": time.time(), "data": {"m": {"context_window": 8000}}}
    )

    with caplog.at_level(logging.WARNING):
        assert await catalog_mod.get_openrouter_catalog() == {"m": {"context_window": 8000}}

    assert not caplog.records
