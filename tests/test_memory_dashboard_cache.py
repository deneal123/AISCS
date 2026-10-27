"""Дашборд семантической памяти кэшируется — но не ценой свежести.

Замер: вызов в MemOS занимает 124-172 мс на КАЖДОЕ открытие панели (сеть до сайдкара,
прогрев не помогает — факты из Postgres после прогрева отдаются за 3 мс). Фронт
запрашивает дашборд вторым запросом, после фактов, поэтому блок семантической памяти
появляется заметно позже остальной панели.

TTL — НЕ единственный механизм свежести. Содержимое MemOS меняется после каждого
разговора и ручной правки фактов: кэш сбрасывается после всех успешных операций записи.
"""

from __future__ import annotations

import json

import pytest

from service.services.analytics.application.memory import cache as memory_cache
from service.services.analytics.application.memory.service import MemoryService
from service.shared.memory_outcomes import MemoryWriteResult


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.gets = 0

    async def get(self, key):
        self.gets += 1
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttls[key] = ex

    async def delete(self, key):
        self.store.pop(key, None)


class _Integration:
    available = True

    def __init__(self, payload=None):
        self.calls = 0
        self._payload = payload if payload is not None else {"text": 3, "pref": 1}

    async def dashboard(self, *, user_id):
        self.calls += 1
        return dict(self._payload)

    async def save_messages(self, *, user_id, messages, metadata=None):
        return MemoryWriteResult.CONFIRMED


class _FactsRepo:
    def __init__(self):
        self.facts = []
        self.deleted = 0

    async def upsert_fact(self, **kwargs):
        self.facts.append(kwargs)

    async def delete_fact(self, *, user_id, fact_id):
        self.deleted += 1
        return True


@pytest.fixture()
def redis(monkeypatch):
    """Патчим Redis в модуле кэша, где он фактически читается и пишется."""
    fake = _FakeRedis()
    monkeypatch.setattr(memory_cache, "_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_second_open_does_not_hit_memos(redis):
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    first = await svc.dashboard("u1")
    second = await svc.dashboard("u1")

    assert first == second
    assert integration.calls == 1


@pytest.mark.asyncio
async def test_cached_value_has_a_ttl(redis):
    await MemoryService(integration=_Integration(), facts_repo=object()).dashboard("u1")

    assert all(ttl and ttl > 0 for ttl in redis.ttls.values())


@pytest.mark.asyncio
async def test_writing_conversation_invalidates_cache(redis):
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.remember_conversation("u1", [{"role": "user", "content": "новое сообщение"}])
    await svc.dashboard("u1")

    assert integration.calls == 2


@pytest.mark.asyncio
async def test_writing_fact_invalidates_cache(redis):
    integration = _Integration()
    repo = _FactsRepo()
    svc = MemoryService(integration=integration, facts_repo=repo)

    await svc.dashboard("u1")
    added = await svc.add_fact("u1", "preference", "Язык", "Русский")
    await svc.dashboard("u1")

    assert added["id"]
    assert integration.calls == 2


@pytest.mark.asyncio
async def test_deleting_fact_invalidates_cache(redis):
    integration = _Integration()
    repo = _FactsRepo()
    svc = MemoryService(integration=integration, facts_repo=repo)

    await svc.dashboard("u1")
    assert await svc.delete_fact("u1", "fact-1")
    await svc.dashboard("u1")

    assert integration.calls == 2


@pytest.mark.asyncio
async def test_empty_answer_is_not_cached(redis):
    integration = _Integration(payload={})
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.dashboard("u1")

    assert integration.calls == 2
    assert not redis.store


@pytest.mark.asyncio
async def test_users_do_not_share_the_cache(redis):
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.dashboard("u2")

    assert integration.calls == 2
    assert len(redis.store) == 2


@pytest.mark.asyncio
async def test_redis_outage_degrades_to_the_old_behaviour(monkeypatch):
    monkeypatch.setattr(memory_cache, "_redis", lambda: None)
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}
    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}
    assert integration.calls == 2


@pytest.mark.asyncio
async def test_broken_cache_entry_does_not_break_the_panel(redis):
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())
    redis.store[memory_cache.key("user:u1")] = "не json"

    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}


@pytest.mark.asyncio
async def test_cached_payload_round_trips(redis):
    svc = MemoryService(integration=_Integration(payload={"тип": "текст"}), facts_repo=object())

    await svc.dashboard("u1")
    stored = json.loads(next(iter(redis.store.values())))

    assert stored == {"тип": "текст"}
