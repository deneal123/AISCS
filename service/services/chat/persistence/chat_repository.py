import json
import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from service.infrastructure.database.postgresql import PgConnector

logger = logging.getLogger(__name__)


def _lookup_id(thread_id: str | None) -> str | None:
    """Идентификатор треда, годный для поиска. ``None`` — такого треда быть НЕ МОЖЕТ.

    🔴 `chat_threads.thread_id` — колонка типа `uuid`. Строка вроде `nope` не «не
    найдена», а НЕПРЕДСТАВИМА: Postgres отвергает такой запрос ошибкой типа, драйвер
    поднимает её наверх, и наружу уезжает 500 — то есть «сломался сервер» вместо «такого
    диалога нет». Найдено живым прогоном подстановкой мусора в путь.

    ⚠️ Проверять надо ЗДЕСЬ, а не в каждом маршруте: их у треда с десяток, и правило про
    форму ключа принадлежит тому слою, который знает тип колонки. Копия в маршрутах
    однажды разошлась бы с колонкой — а тут расходиться не с чем.
    """
    value = str(thread_id or "").strip()
    if not value:
        return None
    try:
        UUID(value)
    except ValueError:
        return None
    return value


class ChatRepository:
    """Repository encapsulating DB access for chat threads and messages.

    The PgConnector is injected by the composition root so that the shared
    connection pool is reused (matching the other repositories' DI pattern).
    """

    def __init__(self, connector: PgConnector) -> None:
        self._connector = connector

    def _get_connector(self) -> PgConnector:
        return self._connector

    async def create_thread(
        self,
        user_id: int | None,
        title: str | None,
        thread_id: str | None = None,
    ) -> tuple[str, object | None]:
        thread_uuid = thread_id or str(uuid4())
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            # Use RETURNING created_at so callers can return a proper timestamp
            res = await session.execute(
                text(
                    "INSERT INTO profile.chat_threads "
                    "(thread_id, user_id, title, created_at, updated_at) "
                    "VALUES (:thread_id, :user_id, :title, NOW(), NOW()) RETURNING created_at"
                ),
                {"thread_id": thread_uuid, "user_id": user_id, "title": title},
            )
            # Attempt to fetch returned created_at; fall back to selecting it explicitly later
            row = res.first()
            created_at = row[0] if row else None
            await session.commit()
        # Return a tuple (thread_uuid, created_at) so callers can decide how to format
        return thread_uuid, created_at

    async def get_thread_pk(self, thread_id: str) -> int | None:
        lookup = _lookup_id(thread_id)
        if lookup is None:
            return None
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            # SQLAlchemy 2.0 requires textual SQL to be wrapped with text(...)
            res = await session.execute(
                text("SELECT id FROM profile.chat_threads WHERE thread_id = :thread_id"),
                {"thread_id": lookup},
            )
            row = res.first()
            return row[0] if row else None

    async def get_thread_owner(self, thread_id: str) -> int | None:
        lookup = _lookup_id(thread_id)
        if lookup is None:
            return None
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            res = await session.execute(
                text("SELECT user_id FROM profile.chat_threads WHERE thread_id = :thread_id"),
                {"thread_id": lookup},
            )
            row = res.first()
            return row[0] if row else None

    async def insert_message(
        self,
        thread_pk: int,
        sender: str,
        content: str,
        message_id: str | None = None,
        user_id: int | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Записать сообщение. ``metadata`` — вложения реплики и прочее, что переживает F5.

        🔴 Колонки `metadata` в этом INSERT не было вовсе: фолбэк-путь (прогон без
        воркера) писал реплику пользователя без вложений, и приложенный файл исчезал
        при перезагрузке страницы. Воркер её заполнял, фолбэк — нет, и разница была
        невидима: оба писали в одну таблицу.
        """
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            await session.execute(
                text(
                    "INSERT INTO profile.chat_messages "
                    '(message_id, thread_id, user_id, sender, content, "metadata", created_at) '
                    "VALUES (:mid, :tpk, :uid, :sender, :content, CAST(:meta AS JSONB), NOW())"
                ),
                {
                    "mid": message_id or str(uuid4()),
                    "tpk": thread_pk,
                    "uid": user_id,
                    "sender": sender,
                    "content": content,
                    "meta": json.dumps(metadata or {}, ensure_ascii=False),
                },
            )
            await session.commit()

    async def fetch_messages(
        self,
        thread_pk: int,
        limit: int,
        offset: int,
        # ⚠️ Аннотация устарела: SELECT ниже отдаёт ЧЕТЫРЕ колонки (добавилась
        # `metadata`), а тип обещал кортеж из трёх. Потребитель уже читает `row[3]`
        # под защитой `len(row) > 3`. Возвращаем то, что реально приходит из
        # SQLAlchemy, а не выдуманную форму.
    ) -> Sequence[Any]:
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            res = await session.execute(
                text(
                    'SELECT sender, content, created_at, "metadata" FROM profile.chat_messages '
                    "WHERE thread_id = :tpk ORDER BY created_at LIMIT :lim OFFSET :off"
                ),
                {"tpk": thread_pk, "lim": limit, "off": offset},
            )
            return res.fetchall()

    async def list_threads(self, user_id: int | None, limit: int, offset: int):
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            if user_id is None:
                res = await session.execute(
                    text(
                        "SELECT thread_id, title, created_at, updated_at "
                        "FROM profile.chat_threads "
                        "ORDER BY updated_at DESC NULLS LAST LIMIT :lim OFFSET :off"
                    ),
                    {"lim": limit, "off": offset},
                )
            else:
                res = await session.execute(
                    text(
                        "SELECT thread_id, title, created_at, updated_at "
                        "FROM profile.chat_threads WHERE user_id = :uid "
                        "ORDER BY updated_at DESC NULLS LAST LIMIT :lim OFFSET :off"
                    ),
                    {"lim": limit, "off": offset, "uid": user_id},
                )
            return res.fetchall()

    async def delete_thread(self, thread_id: str) -> int:
        """Delete thread by external thread_id. Returns number of rows deleted from chat_threads."""
        lookup = _lookup_id(thread_id)
        if lookup is None:
            return 0
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            # Delete thread (messages cascade via FK)
            res = await session.execute(
                text("DELETE FROM profile.chat_threads WHERE thread_id = :tid RETURNING id"),
                {"tid": lookup},
            )
            await session.commit()
            # rowcount is not always available; inspect `res.first()`
            first = res.first()
            return 1 if first else 0

    async def update_thread_title(self, thread_id: str, title: str) -> int:
        """Rename thread by external thread_id. Returns number of rows updated."""
        lookup = _lookup_id(thread_id)
        if lookup is None:
            return 0
        connector = self._get_connector()
        async with connector.get_session_context() as session:
            res = await session.execute(
                text(
                    "UPDATE profile.chat_threads SET title = :title, updated_at = NOW() "
                    "WHERE thread_id = :tid RETURNING id"
                ),
                {"tid": lookup, "title": title},
            )
            await session.commit()
            first = res.first()
            return 1 if first else 0
