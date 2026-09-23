"""Дашборд семантической памяти кэшируется — но не ценой свежести.

Замер: вызов в MemOS занимает 124-172 мс на КАЖДОЕ открытие панели (сеть до сайдкара,
прогрев не помогает — факты из Postgres после прогрева отдаются за 3 мс). Фронт
запрашивает дашборд вторым запросом, после фактов, поэтому блок семантической памяти
появляется заметно позже остальной панели.

🔴 TTL — НЕ единственный механизм, и это принципиально. Содержимое MemOS меняется после
каждого разговора; кэш только по времени означал бы, что человек поговорил, открыл
панель и увидел прежние счётчики. Со стороны это «память не сохранилась» — то есть
ошибка страшнее той задержки, которую мы убираем.
"""

from __future__ import annotations

import json

import pytest

from service.services.analytics.application import memory_cache
from service.services.analytics.application.memory_service import MemoryService


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
        return None


@pytest.fixture()
def redis(monkeypatch):
    """⚠️ Патчим ТАМ, ГДЕ ЧИТАЮТ — в модуле кэша, а не в сервисе.

    Хелперы переехали из `MemoryService` в `memory_cache`, и патч по старому адресу
    молча перестал бы действовать: тесты стали бы ходить в настоящий Redis и проходить
    по другой причине.
    """
    fake = _FakeRedis()
    monkeypatch.setattr(memory_cache, "_redis", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_second_open_does_not_hit_memos(redis):
    """🔴 ГЛАВНОЕ: повторное открытие панели не ходит в сайдкар."""
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    first = await svc.dashboard("u1")
    second = await svc.dashboard("u1")

    assert first == second
    assert integration.calls == 1, "второй запрос всё равно ушёл в MemOS — кэш не работает"


@pytest.mark.asyncio
async def test_cached_value_has_a_ttl(redis):
    """Страховка на изменения мимо нас: вечная запись однажды станет неверной навсегда."""
    await MemoryService(integration=_Integration(), facts_repo=object()).dashboard("u1")

    assert all(ttl and ttl > 0 for ttl in redis.ttls.values())


@pytest.mark.asyncio
async def test_writing_to_memory_invalidates_the_cache(redis):
    """🔴 Поговорил → открыл панель → видит НОВОЕ. Иначе это «память не сохранилась»."""
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.remember_conversation("u1", [{"role": "user", "content": "новое сообщение"}])
    await svc.dashboard("u1")

    assert integration.calls == 2, "после записи в память дашборд отдался из устаревшего кэша"


@pytest.mark.asyncio
async def test_empty_answer_is_not_cached(redis):
    """Пусто значит «не memos ИЛИ ещё не ответил» — запомнить это = спрятать память."""
    integration = _Integration(payload={})
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.dashboard("u1")

    assert integration.calls == 2
    assert not redis.store


@pytest.mark.asyncio
async def test_users_do_not_share_the_cache(redis):
    """Ключ на пользователя: чужие счётчики памяти — это утечка, а не неточность."""
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    await svc.dashboard("u1")
    await svc.dashboard("u2")

    assert integration.calls == 2
    assert len(redis.store) == 2


@pytest.mark.asyncio
async def test_redis_outage_degrades_to_the_old_behaviour(monkeypatch):
    """Кэш необязателен: без Redis панель работает как раньше, просто медленнее."""
    monkeypatch.setattr(memory_cache, "_redis", lambda: None)
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())

    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}
    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}
    assert integration.calls == 2


@pytest.mark.asyncio
async def test_broken_cache_entry_does_not_break_the_panel(redis):
    """В Redis мог остаться мусор от прежней версии — читаем мимо него, а не падаем."""
    integration = _Integration()
    svc = MemoryService(integration=integration, facts_repo=object())
    redis.store[memory_cache.key("user:u1")] = "не json"

    assert await svc.dashboard("u1") == {"text": 3, "pref": 1}


@pytest.mark.asyncio
async def test_cached_payload_round_trips(redis):
    """Кириллица в счётчиках не должна превращаться в escape-последовательности."""
    svc = MemoryService(integration=_Integration(payload={"тип": "текст"}), facts_repo=object())

    await svc.dashboard("u1")
    stored = json.loads(next(iter(redis.store.values())))

    assert stored == {"тип": "текст"}
