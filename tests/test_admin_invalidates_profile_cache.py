"""Инвалидация кэша профиля админом попадает В ТОТ ЖЕ namespace, что и запись.

⚠️ БЫЛА NO-OP. `AdminService._invalidate_profile_cache` сбрасывал `"profile:id"` /
`"profile:email"`, а `ProfileService` хранит под `"profile:id:v2"` / `"profile:email:v2"`
— суффикс `:v2` добавили при миграции формы кэша и не обновили инвалидатор. Промах мимо
ключа: сброса не происходило, кэш жил до истечения TTL.

Наружу: админ блокирует пользователя (`set_active(False)`), а его сессия продолжает
работать до конца TTL, потому что `is_active` в кэше профиля не сбросился. Комментарий в
коде обещал ровно то, чего он уже не делал.

## Почему страж сравнивает namespace, а не строки

Строку `"profile:id:v2"` в тесте продублировать — значит завести ТРЕТЬЮ копию, которая
разъедется так же. Поэтому проверяется инвариант: инвалидатор обязан бить в те же
namespace-константы, под которыми пишет `ProfileService`. Разъедутся снова — тест
покраснеет в тот же коммит.
"""

from __future__ import annotations

import pytest

from service.services.profile.application.profile_service import (
    PROFILE_BY_EMAIL_NAMESPACE,
    PROFILE_BY_ID_NAMESPACE,
)


class _SpyCache:
    """Кэш, запоминающий, какие namespace ему велели инвалидировать."""

    def __init__(self):
        self.invalidated: list[tuple[str, str]] = []

    async def invalidate(self, namespace: str, key: str) -> None:
        self.invalidated.append((namespace, key))


def _admin_service(cache):
    """AdminService с подставленным spy-кэшем и без прочих зависимостей."""
    from service.services.admin.application.admin_service import AdminService

    svc = AdminService.__new__(AdminService)
    svc._profile_cache = cache
    return svc


@pytest.mark.asyncio
async def test_invalidation_targets_the_versioned_namespace():
    """⚠️ ГЛАВНОЕ: сброс идёт в `:v2`-namespace, под которым лежит профиль."""
    cache = _SpyCache()

    await _admin_service(cache)._invalidate_profile_cache("user-123", "User@Example.com")

    namespaces = {ns for ns, _ in cache.invalidated}
    assert PROFILE_BY_ID_NAMESPACE in namespaces, (
        f"инвалидация не попала в {PROFILE_BY_ID_NAMESPACE} — сброс промахивается мимо "
        f"ключа, блокировка пользователя не применится до TTL. Сбрасывали: {namespaces}"
    )
    assert PROFILE_BY_EMAIL_NAMESPACE in namespaces


@pytest.mark.asyncio
async def test_email_is_lowercased_like_the_write_side():
    """Ключ по email — в нижнем регистре, иначе не совпадёт с записанным."""
    cache = _SpyCache()

    await _admin_service(cache)._invalidate_profile_cache("u1", "MiXeD@Case.COM")

    email_keys = [key for ns, key in cache.invalidated if ns == PROFILE_BY_EMAIL_NAMESPACE]
    assert email_keys == ["mixed@case.com"], email_keys


@pytest.mark.asyncio
async def test_missing_email_still_invalidates_by_id():
    """Без email сброс по id обязан произойти — id есть всегда."""
    cache = _SpyCache()

    await _admin_service(cache)._invalidate_profile_cache("u1", None)

    assert any(ns == PROFILE_BY_ID_NAMESPACE for ns, _ in cache.invalidated)
    assert not any(ns == PROFILE_BY_EMAIL_NAMESPACE for ns, _ in cache.invalidated)


@pytest.mark.asyncio
async def test_no_cache_is_a_safe_noop():
    """Кэш не сконфигурен — не падаем."""
    svc = _admin_service(None)
    await svc._invalidate_profile_cache("u1", "e@x.com")  # не бросает
