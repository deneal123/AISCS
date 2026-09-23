"""Single-flight на каталог OpenRouter: N параллельных промахов кэша → ОДИН fetch.

`get_openrouter_catalog` на критическом пути (context_budget на КАЖДОМ запросе), а fetch
теперь идёт ЧЕРЕЗ ПРОКСИ (латентнее). Без single-flight холодный процесс под нагрузкой
давал бы N одновременных сетевых перестроений (thundering herd к openrouter.ai).
"""

import asyncio

import pytest

import service.shared.model_catalog as mc


@pytest.fixture(autouse=True)
def _reset_cache():
    saved = dict(mc._cache)
    mc._cache.update(ts=0.0, data={})
    mc._FETCH_LOCK = None  # лок привязан к петле — сбрасываем, чтобы взять свежий на тест
    yield
    mc._cache.clear()
    mc._cache.update(saved)
    mc._FETCH_LOCK = None


@pytest.mark.asyncio
async def test_concurrent_cold_misses_fetch_once(monkeypatch):
    calls = {"n": 0}

    async def _slow_fetch():
        calls["n"] += 1
        await asyncio.sleep(0.05)  # окно, за которое конкуренты успели бы стартовать fetch
        return {"m1": {"context_window": 8000, "capabilities": [], "name": "m1"}}

    monkeypatch.setattr(mc, "_fetch_openrouter", _slow_fetch)

    results = await asyncio.gather(*(mc.get_openrouter_catalog() for _ in range(8)))

    assert calls["n"] == 1, "single-flight нарушен: параллельные промахи дали больше одного fetch"
    assert all(r and "m1" in r for r in results), "все ждавшие получили перестроенный каталог"


@pytest.mark.asyncio
async def test_warm_cache_skips_fetch(monkeypatch):
    """Тёплый кэш — fetch не зовётся вовсе (лок не мешает быстрому пути)."""
    calls = {"n": 0}

    async def _fetch():
        calls["n"] += 1
        return {"x": {}}

    monkeypatch.setattr(mc, "_fetch_openrouter", _fetch)
    mc._cache.update(ts=mc.time.time(), data={"cached": {"name": "cached"}})

    out = await mc.get_openrouter_catalog()
    assert out == {"cached": {"name": "cached"}}
    assert calls["n"] == 0
