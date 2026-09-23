"""Каталог перестраивается ОДИН раз, сколько бы запросов ни пришло одновременно.

⚠️ Замка не было вовсе. В момент истечения TTL все параллельные запросы уходили
перестраивать каталог каждый сам, а перестройка — это `gather` по ПЯТИ провайдерам с
таймаутом на каждого. То есть самый дорогой момент совпадал с самым многолюдным.

Отсутствие замка было задокументировано как «возможные гонки безвредны — перезапись
идемпотентна». Про запись это верно. Про ДУБЛИРОВАНИЕ СЕТЕВОЙ РАБОТЫ — нет: безвредность
результата ничего не говорит о цене его получения.

## Две разные стратегии, и это намеренно

* **Есть устаревший список** — ждать чужого рефреша хуже, чем отдать список
  трёхминутной давности. Поэтому если обновление уже идёт, отдаём устаревшее НЕМЕДЛЕННО.
* **Холодный старт** — отдавать нечего, и очередь уместна: все ждут ОДНУ сборку вместо
  того, чтобы устроить веер по провайдерам.
"""

from __future__ import annotations

import asyncio

import pytest

from service.domain.client.calls import catalog as cat


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    """Каждый тест начинает с пустого кэша и своего замка."""
    monkeypatch.setattr(
        cat,
        "_CATALOG_CACHE",
        {"list": [], "index": {}, "expires": 0.0, "initialized": False},
    )
    monkeypatch.setattr(cat, "_REBUILD_LOCK", None)


def _slow_builder(counter: dict, delay: float = 0.05):
    async def _build(active_provider):
        counter["n"] = counter.get("n", 0) + 1
        await asyncio.sleep(delay)
        return ["model-a", "model-b"], {"model-a": "openai"}

    return _build


@pytest.mark.asyncio
async def test_cold_start_builds_once_for_many_waiters(monkeypatch):
    """⚠️ ГЛАВНОЕ: десять одновременных запросов — одна сборка, а не десять."""
    counter: dict = {}
    monkeypatch.setattr(cat, "build_model_catalog", _slow_builder(counter))

    results = await asyncio.gather(*(cat.get_model_catalog() for _ in range(10)))

    assert counter["n"] == 1, (
        f"каталог собран {counter['n']} раз(а) на 10 одновременных запросов — "
        "в момент истечения TTL это веер по всем провайдерам"
    )
    assert all(r[0] == ["model-a", "model-b"] for r in results), "не все получили результат"


@pytest.mark.asyncio
async def test_stale_is_served_immediately_while_someone_refreshes(monkeypatch):
    """⚠️ При живом устаревшем списке ждать чужой рефреш НЕ надо.

    Иначе single-flight превратился бы в очередь: один обновляет, остальные стоят —
    латентность выросла бы там, где раньше её не было.
    """
    counter: dict = {}
    monkeypatch.setattr(cat, "build_model_catalog", _slow_builder(counter, delay=0.2))
    # Устаревший, но НЕПУСТОЙ кэш.
    cat._CATALOG_CACHE.update(list=["stale"], index={"stale": "mws"}, expires=0.0)

    results = await asyncio.gather(*(cat.get_model_catalog() for _ in range(5)))

    assert counter["n"] == 1, "обновление запущено несколько раз параллельно"
    # Кто-то получил свежий, остальные — устаревший, но НИКТО не ждал зря.
    assert any(r[0] == ["stale"] for r in results), (
        "все встали в очередь за чужим рефрешем вместо мгновенного устаревшего"
    )


@pytest.mark.asyncio
async def test_warm_cache_does_not_rebuild(monkeypatch):
    """Контроль предпосылки: тёплый кэш вообще не трогает сеть."""
    counter: dict = {}
    monkeypatch.setattr(cat, "build_model_catalog", _slow_builder(counter))
    import time

    cat._CATALOG_CACHE.update(list=["warm"], index={}, expires=time.monotonic() + cat._CATALOG_TTL)

    await asyncio.gather(*(cat.get_model_catalog() for _ in range(5)))

    assert counter.get("n", 0) == 0


@pytest.mark.asyncio
async def test_lock_survives_a_new_event_loop():
    """⚠️ Замок не должен ломаться при смене event loop.

    `asyncio.Lock` привязывается к петле при первом использовании и из другой бросает
    RuntimeError. Модуль исторически исполнялся там, где петля своя на задачу, поэтому
    замок хранится ВМЕСТЕ с петлёй: сменилась — берём новый.
    """
    first = cat._rebuild_lock()
    assert cat._rebuild_lock() is first, "в одной петле замок обязан быть тем же"

    def _in_new_loop():
        async def _get():
            return cat._rebuild_lock()

        return asyncio.run(_get())

    second = await asyncio.to_thread(_in_new_loop)
    assert second is not first, "замок из чужой петли переиспользован — будет RuntimeError"
