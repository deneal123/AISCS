"""Кэш каталога моделей: синхронный рефреш, корректный под celery loop-per-task.

Регрессия: фоновый (asyncio.create_task) serve-while-revalidate не работал в
воркерах — задача умирала с петлёй, а expires уже сдвигался, поэтому каталог не
обновлялся весь TTL. Рефреш теперь синхронный; expires двигается только при
успехе/коротком retry, устаревший список отдаётся при таймауте бюджета.
"""

import pytest

# ⚠️ Патчим МОДУЛЬ, который реально владеет кэшем, а не фасад пакета. Пока вся логика
# лежала в `__init__.py`, «фасад» и «владелец» совпадали; после разделения патч по
# фасаду перестал бы что-либо значить. Здесь это вскрылось сразу (AttributeError), но
# в общем случае такая подмена молча ничего не делает — и тест остаётся зелёным.
import service.domain.client.calls.catalog as facade


@pytest.fixture(autouse=True)
def _reset_catalog():
    saved = dict(facade._CATALOG_CACHE)
    facade._CATALOG_CACHE.clear()
    facade._CATALOG_CACHE.update(list=[], index={}, expires=0.0, initialized=False)
    yield
    facade._CATALOG_CACHE.clear()
    facade._CATALOG_CACHE.update(saved)


@pytest.mark.asyncio
async def test_fresh_cache_returns_without_rebuild(monkeypatch) -> None:
    calls = {"n": 0}

    async def _build(_provider):
        calls["n"] += 1
        return ["m1"], {"m1": "p"}

    monkeypatch.setattr(facade, "build_model_catalog", _build)
    facade._CATALOG_CACHE.update(
        list=["cached"], index={"cached": "p"}, expires=facade.time.monotonic() + 100
    )

    lst, _idx = await facade.get_model_catalog()
    assert lst == ["cached"]
    assert calls["n"] == 0  # свежий кэш — rebuild не вызывался


@pytest.mark.asyncio
async def test_cold_start_builds_and_caches(monkeypatch) -> None:
    async def _build(_provider):
        return ["m1", "m2"], {"m1": "p", "m2": "p"}

    monkeypatch.setattr(facade, "build_model_catalog", _build)

    lst, _idx = await facade.get_model_catalog()
    assert lst == ["m1", "m2"]
    assert facade._CATALOG_CACHE["expires"] > facade.time.monotonic()  # expires сдвинут вперёд


@pytest.mark.asyncio
async def test_rebuild_failure_serves_last_known_and_short_retry(monkeypatch) -> None:
    facade._CATALOG_CACHE.update(list=["old"], index={"old": "p"}, expires=0.0)  # протух

    async def _build(_provider):
        raise RuntimeError("providers down")

    monkeypatch.setattr(facade, "build_model_catalog", _build)

    lst, _idx = await facade.get_model_catalog()
    assert lst == ["old"]  # отдаём последний известный, а не пусто
    remaining = facade._CATALOG_CACHE["expires"] - facade.time.monotonic()
    assert 0 < remaining <= facade._CATALOG_RETRY_TTL + 1  # короткий retry, не полный TTL


@pytest.mark.asyncio
async def test_successful_empty_result_replaces_last_known(monkeypatch) -> None:
    facade._CATALOG_CACHE.update(list=["old"], index={"old": "p"}, expires=0.0)
    calls = 0

    async def _build(_provider):
        nonlocal calls
        calls += 1
        return [], {}

    monkeypatch.setattr(facade, "build_model_catalog", _build)

    lst, _idx = await facade.get_model_catalog()
    assert lst == []
    assert _idx == {}
    assert facade._CATALOG_CACHE["list"] == []
    assert facade._CATALOG_CACHE["expires"] > facade.time.monotonic()

    cached, cached_index = await facade.get_model_catalog()
    assert cached == [] and cached_index == {}
    assert calls == 1


def test_background_refresh_machinery_removed() -> None:
    # Фоновый serve-stale удалён (ломался под celery loop-per-task).
    assert not hasattr(facade, "_spawn_catalog_refresh")
    assert "refreshing" not in facade._CATALOG_CACHE


def test_explicit_invalidation_drops_even_authoritative_empty_state() -> None:
    facade._CATALOG_CACHE.update(
        list=[],
        index={},
        expires=facade.time.monotonic() + 100,
        initialized=True,
    )

    facade.invalidate_model_catalog()

    assert facade._CATALOG_CACHE == {
        "list": [],
        "index": {},
        "expires": 0.0,
        "initialized": False,
    }
