"""Регрессии реального worker-контракта Redis и скользящего окна истории."""

import json
from unittest.mock import AsyncMock

import pytest

from service.services.chat.infrastructure.context import summary_cache as cache
from service.services.chat.infrastructure.context.summary import (
    get_or_build_history_summary,
    read_cached_summary,
    summarized_history,
)


class Redis:
    def __init__(self):
        self.values = {}
        self.unknown_lock = False
        self.unknown_publish = False

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if nx and self.unknown_lock:
            raise TimeoutError
        return True

    def eval(self, script, count, *args):
        lock = args[0]
        token = args[count]
        if self.values.get(lock) != token:
            return 0
        if script == cache.PUBLISH:
            self.values[args[1]] = args[3]
        del self.values[lock]
        if script == cache.PUBLISH and self.unknown_publish:
            raise TimeoutError
        return 1


def history(start=0, end=200):
    return [{"role": "user", "content": f"Реплика {i}"} for i in range(start, end)]


async def build(redis, model, items=None):
    return await get_or_build_history_summary(
        items=items if items is not None else history(),
        session_id="t",
        redis_client=redis,
        summarizer=model,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("async_client", [False, True])
async def test_worker_sync_and_api_async_clients_cache_once(async_client):
    redis = Redis()
    if async_client:
        for method in ("get", "set", "eval"):
            setattr(redis, method, AsyncMock(side_effect=getattr(redis, method)))
    model = AsyncMock(return_value="Подтверждённое резюме")
    assert await build(redis, model) == "Подтверждённое резюме"
    assert await read_cached_summary("t", redis) == "Подтверждённое резюме"
    assert await build(redis, model) == "Подтверждённое резюме"
    assert model.await_count == 1


@pytest.mark.asyncio
async def test_rotating_full_window_updates_and_keeps_older_summary():
    redis = Redis()
    model = AsyncMock(side_effect=["Ранняя цель", "Ранняя цель и новое решение"])
    await build(redis, model)
    assert await build(redis, model, history(2, 202)) == "Ранняя цель и новое решение"
    messages = model.call_args.args[0]
    assert "Ранняя цель" in messages[0]["content"]
    assert messages[1:] == history(194, 196)


@pytest.mark.asyncio
async def test_edit_same_length_does_not_reuse_summary():
    redis = Redis()
    model = AsyncMock(side_effect=["Старое", "Новое"])
    await build(redis, model)
    changed = history()
    changed[100]["content"] = "Пользователь исправил данные"
    assert await build(redis, model, changed) == "Новое"
    assert model.call_args.args[0] == changed[:-6]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ["повреждённый JSON", json.dumps({"summary": "старое", "covered_upto": 194})]
)
async def test_legacy_or_corrupt_cache_rebuilt(raw):
    redis = Redis()
    redis.values[cache.summary_key("gpthub", "t")] = raw
    model = AsyncMock(return_value="Новое")
    assert await build(redis, model) == "Новое"
    assert model.await_count == 1


@pytest.mark.asyncio
async def test_unknown_lock_ack_never_admits_paid_call():
    redis = Redis()
    redis.unknown_lock = True
    model = AsyncMock(return_value="Нельзя")
    assert await build(redis, model) == ""
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_publish_ack_reads_back_without_paid_repeat():
    redis = Redis()
    redis.unknown_publish = True
    model = AsyncMock(return_value="Сохранено")
    assert await build(redis, model) == ""
    assert await build(redis, model) == "Сохранено"
    assert model.await_count == 1


@pytest.mark.asyncio
async def test_expired_owner_cannot_publish_or_release_new_lease():
    redis = Redis()
    key = cache.summary_key("gpthub", "t")

    async def late(*args, **kwargs):
        redis.values[key + ":building"] = "новый владелец"
        redis.values[key] = json.dumps({"summary": "Новый результат"})
        return "Опоздавший результат"

    assert await build(redis, late) == ""
    assert redis.values[key + ":building"] == "новый владелец"
    assert await read_cached_summary("t", redis) == "Новый результат"


@pytest.mark.asyncio
async def test_second_builder_does_not_run_while_first_owns_lease():
    redis = Redis()
    nested = AsyncMock(return_value="Лишний")

    async def owner(*args, **kwargs):
        assert await build(redis, nested) == ""
        return "Один результат"

    assert await build(redis, owner) == "Один результат"
    nested.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_proven_prefix_removed_when_compaction_lags():
    redis = Redis()
    await build(redis, AsyncMock(return_value="Резюме"))
    items = history(170, 204)
    summary, tail = await summarized_history(items=items, session_id="t", redis_client=redis)
    assert summary == "Резюме"
    assert tail == history(194, 204)  # Десять новых реплик, а не безусловные шесть.
    items[0]["content"] = "Изменено пользователем"
    assert await summarized_history(items=items, session_id="t", redis_client=redis) == ("", items)


@pytest.mark.asyncio
async def test_source_constraint_survives_a_lossy_model_and_rotating_window():
    redis = Redis()
    items = history()
    items[0]["content"] = "Код проекта — Лимонный маяк. Бюджет 42 рубля."
    model = AsyncMock(return_value="Продолжается работа над проектом.")
    summary = await build(redis, model, items)
    assert "42" in summary and "маяк" in summary
    rotated = items[2:] + history(200, 202)
    summary = await build(redis, model, rotated)
    assert "42" in summary and "маяк" in summary
