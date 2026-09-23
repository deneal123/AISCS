"""Общий обзор файлов аккаунта: какой файл в каких диалогах появлялся.

🔴 Отдельная история от рабочего места треда, и владелец назвал её отдельной: там
каталог РАБОЧИЙ и временный (живёт по сроку песочницы), здесь — НАКОПИТЕЛЬНЫЙ и общий,
поверх контекста всех чатов. Путать их нельзя: этот класс ошибки в проекте уже стоил
9880 кредитов, когда поиск шёл в личном графе, а репозиторий лежал в своём.

⚠️ ТОЛЬКО НА ЧТЕНИЕ и только просмотр — окно и навигация, без автоматических выводов по
связям. Начинать с показа, а не с догадок о том, что эти связи значат.

⚠️ Связь «файл ↔ диалог» берётся из МЕТАДАННЫХ СООБЩЕНИЙ, а не из `user_file`: та таблица
про треды не знает вовсе (в ней только владелец и ключ хранилища). Метаданные реплики
пользователя несут имя и тип вложения — и несут их теперь на всех четырёх путях записи
хода, а не только на успешном.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from service.infrastructure.agents_client.ports import resolve_user_uuid
from service.models.auth_models import AuthProfile
from service.shared.security.auth_checker import check_auth

logger = logging.getLogger(__name__)

files_overview_router = APIRouter(prefix="/api/files-overview")

# Потолок на выборку. Обзор — это картина, а не выгрузка: тысяча строк не читается
# человеком и не помещается в окно.
MAX_ROWS = 500

_SQL = text(
    """
    SELECT a->>'filename'   AS filename,
           a->>'file_type'  AS file_type,
           t.thread_id      AS thread_id,
           t.title          AS title,
           MAX(m.created_at) AS last_at,
           COUNT(*)          AS mentions
    FROM profile.chat_messages m
    JOIN profile.chat_threads t ON t.id = m.thread_id
    CROSS JOIN LATERAL jsonb_array_elements(
        COALESCE(m."metadata"->'attachments', '[]'::jsonb)
    ) AS a
    WHERE t.user_id = :user_id
      AND m.sender = 'user'
      AND COALESCE(a->>'filename', '') <> ''
    GROUP BY 1, 2, 3, 4
    ORDER BY last_at DESC
    LIMIT :limit
    """
)


@files_overview_router.get("")
async def files_overview(
    profile: Annotated[AuthProfile, Depends(check_auth)],
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = 200,
) -> dict:
    """Файлы аккаунта и диалоги, в которых они появлялись.

    Fail-open по ДОСТУПНОСТИ: сбой чтения отдаёт пустой обзор, а не 500 — окно просмотра
    не должно ронять страницу.
    """
    user_uuid = resolve_user_uuid(str(profile.user_id), anonymous_fallback=False)
    if user_uuid is None:
        return {"files": []}

    pg = _connector()
    try:
        async with pg.get_session_context() as session:
            rows = (await session.execute(_SQL, {"user_id": user_uuid, "limit": limit})).all()
    except Exception:
        logger.warning("обзор файлов аккаунта не собран", exc_info=True)
        return {"files": []}

    grouped: dict[str, dict] = {}
    for filename, file_type, thread_id, title, last_at, mentions in rows:
        item = grouped.setdefault(
            filename, {"filename": filename, "file_type": file_type or "document", "threads": []}
        )
        item["threads"].append(
            {
                "thread_id": str(thread_id),
                "title": title or "Диалог",
                "at": last_at.isoformat() if hasattr(last_at, "isoformat") else str(last_at),
                "mentions": int(mentions or 0),
            }
        )
    return {"files": list(grouped.values())}


def _connector():
    from service.services.chat.infrastructure.chat_worker.factory import (
        ChatWorkerDependencyFactory,
    )
    from service.settings import config

    return ChatWorkerDependencyFactory().create_pg_connector(config)
