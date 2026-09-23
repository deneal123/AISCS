"""Персональный канал уведомлений: publisher, имя канала, публикация при пополнении.

⚠️ ЗАЧЕМ ЭТО ВООБЩЕ ПОЯВИЛОСЬ. Баланс кредитов backend НЕ кэширует — читается живьём из
БД. Но фронт перезапрашивал его только при старте сессии, после ответа модели и при
возврате на вкладку. Пополнение админом происходит ВНЕ сессии пользователя, и ни одно из
этих событий его не триггерит — баланс появлялся с задержкой. Существующие WS
(chat/jobs) привязаны к job_id и живут лишь во время активного запроса, туда не
доставить. Отсюда персональный per-user канал.

⚠️ ЭТО ОПТИМИЗАЦИЯ, А НЕ ИСТОЧНИК ПРАВДЫ. Канал только подсказывает «перечитай баланс»;
само значение всегда из БД. Поэтому доставка НЕ гарантированная (pub/sub), и публикация
FAIL-SOFT: отказ канала не должен ронять уже состоявшееся пополнение.
"""

from __future__ import annotations

import pytest

from service.infrastructure.messaging.user_events import (
    EVENT_BALANCE_REFRESH,
    publish_user_event,
    user_events_channel,
)


class _SpyRedis:
    def __init__(self, *, fail: bool = False):
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, payload: str) -> None:
        if self.fail:
            raise ConnectionError("redis лёг")
        self.published.append((channel, payload))


def test_channel_name_is_per_user_and_stable():
    """Имя канала — одно на publisher и подписчика: разъедутся — пуш молча не дойдёт."""
    assert user_events_channel("u1") == "user:u1:events"
    assert user_events_channel("u1") != user_events_channel("u2")


@pytest.mark.asyncio
async def test_publish_sends_typed_event_to_the_user_channel():
    redis = _SpyRedis()

    await publish_user_event(redis, "u1", EVENT_BALANCE_REFRESH)

    assert len(redis.published) == 1
    channel, payload = redis.published[0]
    assert channel == "user:u1:events"
    import json

    assert json.loads(payload)["type"] == EVENT_BALANCE_REFRESH


@pytest.mark.asyncio
async def test_publish_is_fail_soft():
    """⚠️ Отказ pub/sub не должен ронять вызывающего.

    Публикуется ПОСЛЕ денежной операции: пополнение уже в БД. Упади канал — пользователь
    просто увидит баланс позже, как раньше; исключение отсюда убило бы успешный запрос.
    """
    await publish_user_event(_SpyRedis(fail=True), "u1", EVENT_BALANCE_REFRESH)  # не бросает


@pytest.mark.asyncio
async def test_no_redis_and_no_user_are_safe():
    await publish_user_event(None, "u1", EVENT_BALANCE_REFRESH)  # redis недоступен
    redis = _SpyRedis()
    await publish_user_event(redis, "", EVENT_BALANCE_REFRESH)  # нет user_id
    assert redis.published == []


# --------------------------------------------------------------------------- #
# Публикация ИМЕННО при пополнении админом — по обоим путям                     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["adjust", "set"])
async def test_admin_topup_publishes_balance_refresh(monkeypatch, route):
    """⚠️ И adjust-credits, и set-balance обязаны дёрнуть канал.

    Два пути пополнения; забыть один — и половина пополнений снова «тормозит». Проверяем
    сам факт публикации в канал пользователя, к которому применили пополнение.
    """
    import service.services.admin.presentation.routers.admin_api as api

    published: list[tuple[str, str]] = []

    async def _spy_publish(redis_client, user_id, event_type, **data):
        published.append((user_id, event_type))

    monkeypatch.setattr(api, "publish_user_event", _spy_publish)

    class _Svc:
        async def adjust_credits(self, **kw):
            return {"balance": 100}

        async def set_topup_credits(self, **kw):
            return {"balance": 100}

    class _Admin:
        user_id = "admin-1"

    if route == "adjust":
        await api.adjust_credits(
            user_id="target-user",
            payload=api.AdjustCreditsRequest(delta=50),
            admin=_Admin(),
            service=_Svc(),
            redis_client=object(),
        )
    else:
        await api.set_balance(
            user_id="target-user",
            payload=api.SetBalanceRequest(balance=50),
            admin=_Admin(),
            service=_Svc(),
            redis_client=object(),
        )

    assert published == [("target-user", EVENT_BALANCE_REFRESH)], (
        f"пополнение по пути '{route}' не уведомило пользователя: {published}"
    )
