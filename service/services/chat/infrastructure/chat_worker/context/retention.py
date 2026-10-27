"""Retention cleanup for durable chat history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text


async def delete_expired_chat_history(pg_connector: Any, cutoff: datetime) -> None:
    """Delete expired messages and then remove their now-empty thread shells."""

    async with pg_connector.get_session_context() as session:
        await session.execute(
            text("DELETE FROM profile.chat_messages WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        await session.execute(
            text(
                "DELETE FROM profile.chat_threads WHERE id NOT IN "
                "(SELECT DISTINCT thread_id FROM profile.chat_messages)"
            )
        )
        await session.commit()


__all__ = ["delete_expired_chat_history"]
