"""Персональный WS-канал пользователя: постоянный, per-user, для лёгких уведомлений.

⚠️ ЗАЧЕМ ОТДЕЛЬНЫЙ КАНАЛ. Существующие WS (`chat_ws`, `jobs_ws`) привязаны к
thread_id/job_id и живут ТОЛЬКО во время активного запроса. Пополнение баланса админом
происходит ровно тогда, когда пользователь НЕ в запросе (иначе баланс обновился бы сам
после ответа модели), — и доставить туда через них нечего: соединения нет.

Этот эндпоинт открывается один раз на пользователя при входе и держится, пока открыта
вкладка. Он НЕ несёт бизнес-данных — только сигналы вида «перезапроси X». Поэтому и
транспорт лёгкий (pub/sub без гарантий доставки): офлайн-пользователь ничего не теряет,
он перечитает при следующем открытии.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, status

from service.composition.state import (
    get_optional_redis_client,
    get_optional_redis_session_store,
)
from service.infrastructure.messaging.user_events import user_events_channel
from service.settings import config
from service.shared.security.auth_validation import AuthValidator

logger = logging.getLogger(__name__)
router = APIRouter()

_ANONYMOUS_USER_ID = "00000000-0000-0000-0000-000000000000"
# Периодический пинг, чтобы прокси/балансировщик не закрыл «молчащее» соединение.
_HEARTBEAT_SEC = 25.0


@router.websocket("/api/users/me/events/ws")
async def user_events_ws(
    websocket: WebSocket,
    session_store: Annotated[Any, Depends(get_optional_redis_session_store)],
    redis_client: Annotated[Any, Depends(get_optional_redis_client)],
) -> None:
    """Персональный поток уведомлений. Аутентификация — как у остальных WS."""
    auth_validator = AuthValidator(config.auth)
    session = await auth_validator.authenticate_websocket(websocket, session_store)
    user_id = str((session or {}).get("user_id") or "")
    if not session or not user_id or user_id == _ANONYMOUS_USER_ID:
        # Анонимному персональный канал не положен: событий для него нет, а держать
        # соединение — только занимать сокет.
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    if redis_client is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    channel = user_events_channel(user_id)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    logger.info("user_events_ws: user=%s subscribed", user_id)

    async def _drain_incoming() -> None:
        """Клиент нам ничего осмысленного не шлёт, но обрыв должен разбудить нас сразу.

        Без чтения входящих закрытие вкладки заметилось бы только на следующем пинге —
        до `_HEARTBEAT_SEC` висящего соединения на пустом месте.
        """
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass

    incoming = asyncio.create_task(_drain_incoming())
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_HEARTBEAT_SEC
            )
            if incoming.done():
                break  # клиент отключился
            if message is None:
                # Тишина за интервал — шлём пинг, заодно ловим мёртвое соединение.
                await websocket.send_json({"type": "heartbeat"})
                continue
            data = message.get("data")
            try:
                payload = json.loads(data) if isinstance(data, (str, bytes)) else data
            except Exception:
                payload = {"type": "unknown"}
            await websocket.send_json(payload)
    except Exception:
        logger.debug("user_events_ws: loop ended for user=%s", user_id, exc_info=True)
    finally:
        incoming.cancel()
        try:
            await incoming
        except asyncio.CancelledError:
            pass
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            logger.debug("user_events_ws: cleanup failed", exc_info=True)
        try:
            await websocket.close()
        except Exception:
            pass
