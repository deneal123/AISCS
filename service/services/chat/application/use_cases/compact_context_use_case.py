"""Ручная компактизация контекста (клик по кольцу-индикатору).

Форсированно сворачивает историю треда в саммери → пишет в долговременную память
MemOS + кэширует саммери (его читает процессор для обрезки живого контекста). В
отличие от авто-компактизации (порог ``summary_trigger_messages`` в воркере), здесь
сжимаем даже относительно короткий диалог. Fail-open.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class CompactContextUseCase:
    async def execute(self, *, thread_id: str, user_id: str | None) -> dict[str, Any]:
        if not thread_id or not user_id:
            return {"ok": False, "reason": "no_thread_or_user"}

        from service.infrastructure.cache.redis_manager import RedisManager
        from service.infrastructure.database.postgresql import PgConnector
        from service.services.analytics.application.memory_service import MemoryService
        from service.services.chat.infrastructure.agent_context import (
            gateway_summarizer,
            get_or_build_history_summary,
        )
        from service.services.chat.persistence.chat_worker_repository import ChatWorkerRepository
        from service.settings import config

        try:
            redis = RedisManager(config.redis).get_client()
            connector = PgConnector(config.pg)
            items: list[dict[str, Any]] = []
            async for db in connector.get_session():
                items = await ChatWorkerRepository().restore_thread_history(
                    db_session=db, thread_id=str(thread_id), session_data=None, history_limit=200
                )
                break
            if not items:
                return {"ok": False, "reason": "empty"}

            summary = await get_or_build_history_summary(
                items=items,
                session_id=str(thread_id),
                redis_client=redis,
                trigger_messages=1,  # форс: сжимаем даже короткий диалог
                keep_recent=int(config.agents.summary_keep_recent),
                max_tokens=int(config.agents.summary_max_tokens),
                # LLM-часть делегируется сайдкару: провайдеров backend не знает.
                summarizer=gateway_summarizer,
            )
            if not summary:
                return {"ok": False, "reason": "no_summary"}

            # В MemOS — только при изменении саммери (дедуп по хэшу), как в авто-пути.
            digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
            mark_key = f"gpthub:memos_summary_hash:{thread_id}"
            try:
                prev = await redis.get(mark_key)
                prev = prev.decode() if isinstance(prev, (bytes, bytearray)) else prev
            except Exception:
                prev = None
            if prev != digest:
                await MemoryService().remember_conversation(
                    str(user_id),
                    [{"role": "user", "content": f"Резюме предыдущего диалога: {summary}"}],
                    metadata={"kind": "summary", "thread_id": str(thread_id)},
                )
                try:
                    await redis.set(mark_key, digest)
                except Exception:
                    logger.debug("compaction hash marker write failed", exc_info=True)

            # Отдаём и сам текст резюме (усечённый) — фронт покажет его в «шторке» под
            # разделителем сжатия, чтобы пользователь мог увидеть, во что свёрнут диалог.
            return {
                "ok": True,
                "summary_len": len(summary),
                "messages": len(items),
                "summary": summary[:8000],
            }
        except Exception:
            logger.debug("manual compaction failed", exc_info=True)
            return {"ok": False, "reason": "error"}
