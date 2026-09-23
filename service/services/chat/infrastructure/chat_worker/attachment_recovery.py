"""Server-side recovery for an attachment whose client context was lost."""

from __future__ import annotations

import logging
from typing import Any

from service.services.chat.infrastructure.chat_worker.turn_context import decode_as_text

logger = logging.getLogger(__name__)


async def recover_attachment_text(
    pg_connector: Any,
    config: Any,
    user_id: str | None,
) -> str:
    """Best-effort recovery of the latest owned file without exposing its identity."""

    if not user_id:
        return ""
    try:
        from sqlalchemy import select

        from service.infrastructure.agents_client.ports import resolve_user_uuid
        from service.models.db.db_models import UserFile
        from service.services.chat.infrastructure.chat_worker.factory import build_file_service
        from service.services.chat.infrastructure.media.opendataloader_parser import (
            OpenDataLoaderParser,
        )

        user_uuid = resolve_user_uuid(user_id, anonymous_fallback=False)
        if user_uuid is None:
            return ""
        async with pg_connector.get_session_context() as session:
            rows = (
                (
                    await session.execute(
                        select(UserFile)
                        .where(UserFile.user_id == user_uuid)
                        .order_by(UserFile.created_at.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            return ""
        storage_key = getattr(rows[0], "file_name", "") or ""
        content = await build_file_service(config, pg_connector).get_file_by_key(
            file_key=storage_key
        )
        if not content:
            return ""

        text = await OpenDataLoaderParser().parse(content, storage_key)
        if not text:
            text = decode_as_text(content)
        if text:
            logger.info(
                "attachment context recovered",
                extra={"component": "chat_worker", "content_chars": len(text)},
            )
        return text or ""
    except Exception:
        logger.warning(
            "attachment context recovery failed",
            extra={"component": "chat_worker", "failure_code": "unavailable"},
        )
        return ""


__all__ = ["recover_attachment_text"]
