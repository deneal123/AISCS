"""Conversation restore and post-commit history compaction helpers."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from service.services.chat.infrastructure.chat_worker import ChatWorkerConversationService
from service.services.chat.persistence.chat_worker_repository import ChatWorkerRepository

logger = logging.getLogger(__name__)


class MemoryUserUnresolved(Exception):
    """The chat has no durable memory owner; fact extraction is skipped."""


async def resolve_memory_user_id(
    *,
    db_session: Any,
    user_id: Any,
    thread_id: str,
) -> str | None:
    return await ChatWorkerConversationService(ChatWorkerRepository()).resolve_memory_user(
        db_session=db_session,
        user_id=user_id,
        thread_id=thread_id,
    )


async def restore_pseudo_session_history(
    *,
    pseudo_session: Any,
    db_session: Any,
    thread_id: str,
    session_data: dict[str, Any] | None,
    history_limit: int = 12,
) -> int:
    return await ChatWorkerConversationService(ChatWorkerRepository()).restore_thread_history(
        pseudo_session=pseudo_session,
        db_session=db_session,
        thread_id=thread_id,
        session_data=session_data,
        history_limit=history_limit,
    )


async def maybe_compact_thread(
    *,
    db_session: Any,
    redis_client: Any,
    config: Any,
    user_id: str,
    thread_id: str,
) -> None:
    """Compact old history and deduplicate the durable memory projection."""

    if not thread_id or not user_id or redis_client is None:
        return
    if not config.agents.history_summary_enabled:
        return

    from service.services.analytics.application.memory_service import MemoryService
    from service.services.chat.infrastructure.agent_context import (
        gateway_summarizer,
        get_or_build_history_summary,
    )

    items = await ChatWorkerRepository().restore_thread_history(
        db_session=db_session,
        thread_id=str(thread_id),
        session_data=None,
        history_limit=200,
    )
    if not items:
        return
    summary = await get_or_build_history_summary(
        items=items,
        session_id=str(thread_id),
        redis_client=redis_client,
        trigger_messages=int(config.agents.summary_trigger_messages),
        keep_recent=int(config.agents.summary_keep_recent),
        max_tokens=int(config.agents.summary_max_tokens),
        summarizer=gateway_summarizer,
    )
    if not summary:
        return

    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:16]
    marker_key = f"gpthub:memos_summary_hash:{thread_id}"
    try:
        previous = await redis_client.get(marker_key)
        previous = previous.decode() if isinstance(previous, (bytes, bytearray)) else previous
    except Exception:
        previous = None
    if previous == digest:
        return

    await MemoryService().remember_conversation(
        str(user_id),
        [{"role": "user", "content": f"Резюме предыдущего диалога: {summary}"}],
        metadata={"kind": "summary", "thread_id": str(thread_id)},
    )
    try:
        await redis_client.set(marker_key, digest)
    except Exception:
        logger.debug(
            "compaction marker persistence failed",
            extra={"component": "chat_worker", "failure_code": "persistence"},
        )


async def extract_and_charge_memory(
    *,
    session: Any,
    pg_connector: Any,
    redis_client: Any,
    config: Any,
    user_id: str | None,
    thread_id: str,
    job_id: str,
    user_text: str,
    resolve_user: Any,
    charge_usage: Any,
    compact_thread: Any,
) -> None:
    """Extract facts and compact history as independent best-effort stages."""

    try:
        memory_user_id = await resolve_user(
            db_session=session,
            user_id=user_id,
            thread_id=thread_id,
        )
        if not memory_user_id:
            raise MemoryUserUnresolved

        from service.services.analytics.application.memory_service import MemoryService

        mem_usage: dict[str, Any] = {}
        await MemoryService().extract_and_save_facts(
            memory_user_id,
            thread_id,
            [{"role": "user", "content": user_text}],
            usage_out=mem_usage,
        )
        await charge_usage(
            pg_connector=pg_connector,
            redis_client=redis_client,
            user_id=user_id,
            mem_usage=mem_usage,
            thread_id=thread_id,
            job_id=job_id,
            config=config,
        )
    except MemoryUserUnresolved:
        logger.debug(
            "memory user unresolved",
            extra={"component": "memory", "failure_code": "owner_unresolved"},
        )
    except Exception:
        logger.debug(
            "memory extraction failed",
            extra={"component": "memory", "failure_code": "unavailable"},
        )

    try:
        await compact_thread(
            db_session=session,
            redis_client=redis_client,
            config=config,
            user_id=str(user_id or ""),
            thread_id=thread_id,
        )
    except Exception:
        logger.debug(
            "thread compaction failed",
            extra={"component": "memory", "failure_code": "unavailable"},
        )


__all__ = [
    "extract_and_charge_memory",
    "maybe_compact_thread",
    "resolve_memory_user_id",
    "restore_pseudo_session_history",
]
