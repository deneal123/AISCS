"""ProviderPolicy: ручной disable + persistent health-блок + объединения.

Фаза 1 отказоустойчивости: провайдер, выключенный админом (disabled) или заблокированный
проверкой (blocked), скрыт у юзеров и не пробуется фейловером. blocked persistent (БД+Redis).
"""

import pytest

from service.domain.client.resilience import provider_policy


class _FakeRedis:
    def __init__(self):
        self.kv = {}

    def set(self, key, value, **kw):
        self.kv[key] = value
        return True

    def delete(self, key):
        self.kv.pop(key, None)
        return 1

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]


class _FakeRepo:
    def __init__(self, initial=None):
        self.store = dict(initial or {})

    async def get_all(self):
        return dict(self.store)

    async def upsert(self, *, key, value, updated_by=None):
        self.store[key] = value


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # Чистое состояние + фейковые Redis/репо на каждый тест.
    provider_policy._BLOCKED.clear()
    fake = _FakeRedis()
    monkeypatch.setattr(provider_policy, "_get_redis", lambda: fake)
    provider_policy.bind(_FakeRepo())
    # Список провайдеров стабилен (не зависит от конфигурации клиентов).
    monkeypatch.setattr(
        provider_policy, "_all_provider_names", lambda: ["openai", "gigachat", "mws", "openrouter"]
    )
    yield fake
    # Прибираем ЗА собой, а не только перед собой. `_BLOCKED` и `_repo` —
    # процесс-глобальные, monkeypatch их не откатывает: в backend'е этот файл гонялся в
    # своём каталоге и сходило с рук, а в общем прогоне сайдкара оставленный блок
    # gigachat выбивал провайдера из каталога у соседних тестов («падает только в
    # полном прогоне»).
    provider_policy._BLOCKED.clear()
    provider_policy.bind(None)


def test_disabled_from_enabled_map(monkeypatch):
    # runtime_settings.get_agents("provider_enabled", ...) → мапа; отсутствие ключа = включён.
    # Снимочный прокси сайдкара вместо admin-модуля backend'а: у сайдкара нет его БД,
    # переопределения приезжают телом `/run`.
    from service.shared import agent_settings as rs_mod

    enabled = {"gigachat": False, "openai": True}
    monkeypatch.setattr(
        rs_mod.runtime_settings,
        "get_agents",
        lambda name, default=None: enabled if name == "provider_enabled" else default,
    )
    assert provider_policy.disabled_providers() == {"gigachat"}


@pytest.mark.asyncio
async def test_set_and_clear_blocked_roundtrip(_isolate):
    await provider_policy.set_blocked("gigachat", "TLS упал")
    assert "gigachat" in await provider_policy.blocked_providers()
    assert _isolate.kv.get("provider:blocked:gigachat") == "blocked"
    assert "TLS упал" not in repr(_isolate.kv)

    await provider_policy.clear_blocked("gigachat")
    assert "gigachat" not in await provider_policy.blocked_providers()
    assert "provider:blocked:gigachat" not in _isolate.kv


@pytest.mark.asyncio
async def test_blocked_persisted_to_db_and_primed():
    # set_blocked пишет в БД; prime в новом процессе восстанавливает блок.
    repo = _FakeRepo()
    provider_policy.bind(repo)
    await provider_policy.set_blocked("mws", "quota")
    assert "mws" in repo.store.get("provider_blocked", {})

    # Симулируем рестарт: чистим память, праймим из той же БД.
    provider_policy._BLOCKED.clear()
    await provider_policy.prime()
    assert "mws" in await provider_policy.blocked_providers()


@pytest.mark.asyncio
async def test_hard_off_is_disabled_union_blocked(monkeypatch):
    monkeypatch.setattr(provider_policy, "disabled_providers", lambda: {"openai"})
    await provider_policy.set_blocked("gigachat", "down")
    hard = await provider_policy.hard_off(["openai", "gigachat", "mws"])
    assert hard == {"openai", "gigachat"}


@pytest.mark.asyncio
async def test_drop_hard_off_can_empty(monkeypatch):
    # Осознанное решение админа/проверки: убираем ВСЕГДА, даже опустошая (в отличие от breaker).
    monkeypatch.setattr(provider_policy, "disabled_providers", lambda: {"openai"})
    await provider_policy.set_blocked("gigachat", "down")
    assert await provider_policy.drop_hard_off(["openai", "gigachat"]) == []
    assert await provider_policy.drop_hard_off(["openai", "mws"]) == ["mws"]
