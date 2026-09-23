from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

# Сколько прочитанных ссылок дописывается к реплике в истории. 🔴 Без этого следующий ход
# не знает, ОТКУДА взялся прошлый ответ: живой кейс — ассистент нашёл вакансию и ответил по
# ней, а на «что можешь про неё сказать» ответил, что описания не видит, и попросил
# прислать ссылку. Дописка даёт ему адрес, который он может дочитать через `fetch_url`.
#
# ⚠️ ПОТОЛОК ЖЁСТКИЙ: история едет в промпт КАЖДЫЙ ход, и полтора десятка ссылок на
# сообщение — это постоянная надбавка к цене каждого хода, а не разовая.
_HISTORY_SOURCES_LIMIT = 5
_HISTORY_SOURCE_URL_MAX = 200

_ANONYMOUS_USER_IDS = {
    "",
    "none",
    "null",
    "anon",
    "anonymous",
    "00000000-0000-0000-0000-000000000000",
}


def _sources_note(meta: Any) -> str:
    """Приписка со ссылками, прочитанными в ТОМ ходу, или пустая строка.

    ⚠️ Дописывается к тексту реплики, а не едет отдельным полем: история уходит в модель
    как `[{role, content}]`, и любое поле рядом с `content` до неё просто не доедет.
    """
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            return ""
    items = (meta or {}).get("sources") if isinstance(meta, dict) else None
    if not isinstance(items, list) or not items:
        return ""
    urls: list[str] = []
    for item in items[:_HISTORY_SOURCES_LIMIT]:
        url = str((item or {}).get("url") or "").strip()[:_HISTORY_SOURCE_URL_MAX]
        if url and url not in urls:
            urls.append(url)
    if not urls:
        return ""
    return "\n[Источники этого ответа: " + ", ".join(urls) + "]"


class ChatWorkerRepository:
    @staticmethod
    def _is_memory_eligible_user(user_id: str | None) -> bool:
        if user_id is None:
            return False
        normalized = str(user_id).strip().lower()
        return normalized not in _ANONYMOUS_USER_IDS

    @staticmethod
    def _normalize_user_uuid(user_id: str | None) -> str | None:
        if user_id is None:
            return None
        value = str(user_id).strip()
        if not value or value.lower() in _ANONYMOUS_USER_IDS:
            return None
        try:
            return str(UUID(value))
        except Exception:
            return None

    async def resolve_memory_user(
        self, *, db_session: Any, user_id: Any, thread_id: str
    ) -> str | None:
        raw_user_id = str(user_id).strip() if user_id is not None else None
        if self._is_memory_eligible_user(raw_user_id):
            return raw_user_id
        if not thread_id:
            return None
        owner_res = await db_session.execute(
            text("SELECT user_id FROM profile.chat_threads WHERE thread_id = :thread_id LIMIT 1"),
            {"thread_id": thread_id},
        )
        owner_user_id = owner_res.scalar_one_or_none()
        owner_str = str(owner_user_id).strip() if owner_user_id is not None else None
        if self._is_memory_eligible_user(owner_str):
            return owner_str
        return None

    async def restore_thread_history(
        self,
        *,
        db_session: Any,
        thread_id: str,
        session_data: dict[str, Any] | None,
        history_limit: int,
    ) -> list[dict[str, Any]]:
        def normalize_role(raw_role: Any) -> str:
            role = str(raw_role or "").strip().lower()
            return "assistant" if role == "agent" else role

        restored_items: list[dict[str, Any]] = []
        raw_history = (
            (session_data or {}).get("history") if isinstance(session_data, dict) else None
        )

        if isinstance(raw_history, list):
            for item in raw_history[-history_limit:]:
                if not isinstance(item, dict):
                    continue
                role = normalize_role(item.get("role"))
                if role not in {"user", "assistant", "system"}:
                    continue
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                restored_items.append(
                    {
                        "role": role,
                        "content": content,
                        "ts": float(item.get("ts") or datetime.now(UTC).timestamp()),
                    }
                )

        if restored_items:
            return restored_items

        res = await db_session.execute(
            text(
                """
                SELECT m.sender, m.content, m.created_at, m.metadata
                FROM profile.chat_messages m
                JOIN profile.chat_threads t ON t.id = m.thread_id
                WHERE t.thread_id = :thread_id
                ORDER BY m.created_at DESC
                LIMIT :lim
                """
            ),
            {"thread_id": thread_id, "lim": max(int(history_limit), 1)},
        )
        rows = list(res.fetchall())
        rows.reverse()

        for sender, content, created_at, meta in rows:
            role = normalize_role(sender)
            if role not in {"user", "assistant", "system"}:
                continue
            txt = str(content or "").strip()
            if not txt:
                continue
            txt += _sources_note(meta)
            try:
                ts = (
                    float(created_at.timestamp())
                    if created_at is not None
                    else datetime.now(UTC).timestamp()
                )
            except Exception:
                ts = datetime.now(UTC).timestamp()
            restored_items.append({"role": role, "content": txt, "ts": ts})

        return restored_items

    async def last_assistant_persona_ids(
        self, *, db_session: Any, thread_id: str
    ) -> list[str] | None:
        """Личности ПОСЛЕДНЕГО ответа ассистента в треде. `None` — ответов ещё не было.

        ⚠️ `None` и `[]` здесь РАЗНОЕ, и разница несущая. `[]` — «прошлый ответ дан без
        личности», `None` — «сравнивать не с чем». Слить их значит объявить сменой роли
        первый же ответ в треде и подмешать в него границу на пустом месте.

        ⚠️ Сортировка по `id`, а НЕ по `created_at`: реплики хода пишутся одной
        транзакцией и делят метку времени до микросекунды (проверено на живых данных —
        у пары «вопрос/ответ» `created_at` совпадает), так что порядок по времени между
        ними не определён.
        """
        res = await db_session.execute(
            text(
                """
                SELECT m.metadata
                FROM profile.chat_messages m
                JOIN profile.chat_threads t ON t.id = m.thread_id
                WHERE t.thread_id = :thread_id AND m.sender IN ('assistant', 'agent')
                ORDER BY m.id DESC
                LIMIT 1
                """
            ),
            {"thread_id": thread_id},
        )
        row = res.fetchone()
        if row is None:
            return None
        meta = row[0]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, ValueError):
                return []
        if not isinstance(meta, dict):
            return []
        raw = meta.get("persona_ids")
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw if str(item or "").strip()]

    async def persist_turn(
        self,
        *,
        db_session: Any,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        user_id: str | None,
        user_metadata: dict | None = None,
        assistant_metadata: dict | None = None,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
    ) -> bool:
        """Записать ход диалога вместе с МЕТАДАННЫМИ.

        Колонка `metadata` (JSONB) в таблице была с самой первой миграции, но в неё
        никогда не писали — поэтому usage, кредиты, вложения и сгенерированные картинки
        жили только в стейте фронта и умирали при перезагрузке страницы. Пользователь
        терял ровно то, за что заплатил.

        `metadata` — зарезервированное имя в SQLAlchemy Declarative, но здесь сырой SQL,
        так что достаточно закавычить.
        """
        normalized_uid = self._normalize_user_uuid(user_id)

        thread_res = await db_session.execute(
            text("SELECT id FROM profile.chat_threads WHERE thread_id = :thread_id LIMIT 1"),
            {"thread_id": thread_id},
        )
        row = thread_res.first()
        if not row:
            # Автозаголовок треда из первого сообщения пользователя (одна строка,
            # ≤60 симв.) — иначе в шапке/сайдбаре светился дефолт "Chat".
            auto_title = str(user_text or "").strip().replace("\n", " ")[:60] or "Chat"
            create_res = await db_session.execute(
                text(
                    """
                    INSERT INTO profile.chat_threads
                        (thread_id, user_id, title, created_at, updated_at)
                    VALUES (:thread_id, :user_id, :title, NOW(), NOW())
                    ON CONFLICT (thread_id)
                    DO UPDATE SET updated_at = NOW()
                    RETURNING id
                    """
                ),
                {
                    "thread_id": thread_id,
                    "user_id": normalized_uid,
                    "title": auto_title,
                },
            )
            row = create_res.first()

        if not row:
            return False

        thread_pk = row[0]

        insert_sql = text(
            """
            INSERT INTO profile.chat_messages
                (message_id, thread_id, user_id, sender, content,
                 content_tokens, "metadata", created_at)
            VALUES (:mid, :tpk, :uid, :sender, :content,
                    :tokens, CAST(:meta AS JSONB), NOW())
            """
        )

        if str(user_text or "").strip():
            await db_session.execute(
                insert_sql,
                {
                    "mid": str(user_message_id or uuid4()),
                    "tpk": thread_pk,
                    "uid": normalized_uid,
                    "sender": "user",
                    "content": str(user_text),
                    "tokens": None,
                    "meta": json.dumps(user_metadata or {}, ensure_ascii=False),
                },
            )

        if str(assistant_text or "").strip():
            meta = assistant_metadata or {}
            usage = meta.get("usage") or {}
            await db_session.execute(
                insert_sql,
                {
                    "mid": str(assistant_message_id or uuid4()),
                    "tpk": thread_pk,
                    "uid": None,
                    "sender": "assistant",
                    "content": str(assistant_text),
                    # content_tokens колонка тоже была и тоже не заполнялась.
                    "tokens": int(usage.get("total") or 0) or None,
                    "meta": json.dumps(meta, ensure_ascii=False),
                },
            )

        return True
