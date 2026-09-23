import logging
from datetime import datetime
from typing import Any

from service.services.chat.domain.mode_offer import expire_mode_offer
from service.shared.repositories.exceptions import RepositoryNotFoundError

logger = logging.getLogger(__name__)


class ChatPersistenceService:
    def __init__(self, repository, file_service=None):
        self.repo = repository
        # Нужен, чтобы перевыпускать пресайн-ссылки на сгенерированные файлы при отдаче
        # истории (см. _refresh_artifact_links). None — просто отдаём что сохранено.
        self.file_service = file_service

    async def create_thread(
        self, user_id: str | int | None, title: str | None, thread_id: str | None = None
    ) -> dict[str, Any]:
        tid, created_at = await self.repo.create_thread(
            user_id=user_id, title=title, thread_id=thread_id
        )
        created_iso = None
        if created_at is not None:
            created_iso = (
                created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
            )
        return {"thread_id": tid, "title": title, "created_at": created_iso}

    async def persist_messages(
        self,
        thread_id: str,
        user_text: str,
        agent_reply: str,
        user_id: str | int | None,
        user_metadata: dict | None = None,
    ) -> None:
        thread_pk = await self.repo.get_thread_pk(thread_id)
        if thread_pk is None:
            return
        await self.repo.insert_message(
            thread_pk=thread_pk,
            sender="user",
            content=user_text,
            user_id=user_id,
            # Вложения реплики. Без них фолбэк-путь терял приложенный файл при F5.
            metadata=user_metadata,
        )
        # Единая роль ассистента на запись — "assistant" (как в воркере
        # _persist_chat_turn). Раньше этот fallback-путь писал "agent", из-за чего в
        # БД смешивались роли одной сущности. Старые "agent"-строки продолжают
        # читаться (нормализация agent→assistant при восстановлении истории; фронт
        # мапит любой не-"user" sender в agent-тип).
        await self.repo.insert_message(
            thread_pk=thread_pk, sender="assistant", content=agent_reply, user_id=None
        )

    async def get_messages(
        self, thread_id: str, page: int = 1, per_page: int = 50
    ) -> dict[str, Any]:
        if page < 1 or per_page < 1 or per_page > 500:
            raise ValueError("Invalid pagination parameters")

        offset = (page - 1) * per_page
        thread_pk = await self.repo.get_thread_pk(thread_id)
        if thread_pk is None:
            raise RepositoryNotFoundError("Thread not found")

        rows = await self.repo.fetch_messages(thread_pk=thread_pk, limit=per_page, offset=offset)
        messages = []
        for row in rows:
            created = row[2]
            created_iso = (
                created.isoformat()
                if isinstance(created, datetime)
                else str(created)
                if created is not None
                else None
            )
            meta = row[3] if len(row) > 3 and isinstance(row[3], dict) else {}
            messages.append(
                {
                    "sender": row[0],
                    "content": row[1],
                    "created_at": created_iso,
                    # Токены, кредиты, время выполнения, вложения и сгенерированные
                    # картинки. Раньше отдавались только sender/content/created_at —
                    # всё остальное умирало при перезагрузке страницы.
                    "metadata": expire_mode_offer(await self._refresh_artifact_links(meta)),
                }
            )
        return {"thread_id": thread_id, "page": page, "per_page": per_page, "messages": messages}

    async def _refresh_artifact_links(self, meta: dict) -> dict:
        """Перевыпустить ссылки на сгенерированные файлы.

        `file_url` — это ПРЕСАЙН, он протухает. Сохранённая намертво ссылка через
        несколько часов отдаст 403, и для пользователя это выглядело бы как «картинка
        опять пропала». Настоящий якорь — `file_key`: по нему выписываем свежую ссылку
        на каждой отдаче истории.

        Fail-open: не смогли перевыпустить — оставляем что было.
        """
        files = meta.get("generated_files") or []
        if not files or self.file_service is None:
            return meta

        refreshed = []
        primary = None
        for item in files:
            if not isinstance(item, dict):
                continue
            key = item.get("file_key")
            url = item.get("file_url")
            if key:
                try:
                    fresh = await self.file_service.get_presigned_url_by_key(file_key=key)
                    if fresh:
                        url = fresh
                except Exception:
                    logger.debug("не удалось перевыпустить ссылку на %s", key, exc_info=True)
            refreshed.append({**item, "file_url": url})
            if primary is None and url:
                primary = url

        out = {**meta, "generated_files": refreshed}
        if primary:
            out["file_url"] = primary
        return out

    async def list_threads(
        self, user_id: str | int | None = None, page: int = 1, per_page: int = 50
    ) -> dict[str, Any]:
        if page < 1 or per_page < 1 or per_page > 500:
            raise ValueError("Invalid pagination parameters")
        offset = (page - 1) * per_page
        rows = await self.repo.list_threads(user_id=user_id, limit=per_page, offset=offset)
        threads = []
        for row in rows:
            created = row[2]
            updated = row[3]
            threads.append(
                {
                    "thread_id": row[0],
                    "title": row[1],
                    "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
                    "updated_at": updated.isoformat() if hasattr(updated, "isoformat") else None,
                }
            )
        return {"page": page, "per_page": per_page, "threads": threads}

    async def delete_thread(self, thread_id: str) -> bool:
        return bool(await self.repo.delete_thread(thread_id))

    async def update_thread_title(self, thread_id: str, title: str) -> bool:
        return bool(await self.repo.update_thread_title(thread_id, title))

    async def get_thread_owner(self, thread_id: str) -> str | int | None:
        return await self.repo.get_thread_owner(thread_id)
