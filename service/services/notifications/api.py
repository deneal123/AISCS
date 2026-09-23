# ruff: noqa: E501 - инлайн-стили HTML-страницы; перенос ломает вёрстку.
"""Отписка от писем.

Эндпоинт ПУБЛИЧНЫЙ и намеренно: ссылка в письме должна работать, даже когда человек не
залогинен — иначе «отписаться» превращается в «войдите, чтобы отписаться», и единственным
рабочим способом остаётся кнопка «спам».

Защита — подпись HMAC, а не авторизация: без неё ссылка вида `?u=<uuid>` позволяла бы
отписать ЛЮБОГО, просто подставив чужой id.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response

from service.composition.state import get_current_container
from service.services.notifications.notification_service import verify_unsubscribe_token
from service.settings import config

logger = logging.getLogger(__name__)
notifications_router = APIRouter(prefix="/api/notifications")

_PAGE = """<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>Отписка — GPTHub</title></head>
<body style="margin:0;background:#0b0d12;color:#e8ecf4;font:400 15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;">
<div style="max-width:440px;margin:96px auto;padding:28px;background:#12151d;border:1px solid #1e2430;border-radius:14px;">
  <div style="font:600 13px/1.4 sans-serif;color:#2D5BFF;letter-spacing:.04em;text-transform:uppercase;">GPTHub</div>
  <h1 style="margin:12px 0 8px;font-size:20px;">{title}</h1>
  <p style="margin:0;color:#a7b0c0;">{body}</p>
</div></body></html>"""


def _page(title: str, body: str) -> Response:
    return Response(
        content=_PAGE.format(title=title, body=body), media_type="text/html; charset=utf-8"
    )


@notifications_router.get("/unsubscribe")
async def unsubscribe(
    u: str = Query(..., description="user id"),
    t: str = Query(..., description="signature"),
) -> Response:
    if not verify_unsubscribe_token(u, t, config.auth.secret):
        raise HTTPException(status_code=403, detail="Недействительная ссылка отписки")

    try:
        service = get_current_container().services.profile_service
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Сервис недоступен") from exc

    # Через сервис, а не UPDATE в обход: профиль кэшируется в Redis на 15 минут, и сырая
    # запись оставила бы в кэше «письма включены» сразу после отписки.
    try:
        changed = await service.unsubscribe_all(UUID(u))
    except ValueError:
        # Токен подписан нами, значит id настоящий — но аккаунт мог быть уже удалён.
        # Показываем ту же страницу: писем человек всё равно больше не получит, а
        # ошибка по ссылке из почты выглядит как «отписаться не дали».
        logger.warning("Отписка по ссылке: пользователь %s не найден", u)
        changed = False

    return _page(
        "Вы отписаны" if changed else "Вы уже отписаны",
        "Мы больше не будем присылать вам письма. Уведомления можно включить обратно в профиле.",
    )
