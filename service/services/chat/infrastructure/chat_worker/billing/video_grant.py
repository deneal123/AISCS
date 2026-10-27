"""Attach a private job grant only after the existing video confirmation gate."""

from __future__ import annotations

import logging
import os
from typing import Any

from service.services.chat.application.video_stt.grants import mint_video_stt_grant

logger = logging.getLogger(__name__)


async def attach_video_stt_grant(
    redis: Any,
    ref: dict[str, Any],
    *,
    user_id: str | None,
    thread_id: str | None,
    task_id: str | None,
    confirmed: bool,
) -> None:
    if not confirmed or not task_id or not ref.get("coordination_capability"):
        return
    try:
        token = await mint_video_stt_grant(
            redis,
            owner_id=str(user_id),
            task_id=str(task_id),
            thread_id=str(thread_id),
            capability=ref["coordination_capability"],
            confirmed=True,
        )
        base = os.environ.get("WORKSPACE_COORDINATOR_URL", "http://backend:8000").rstrip("/")
        ref["video_stt"] = {"grant": token, "endpoint": base + "/internal/video-stt/from-video"}
    except Exception:
        logger.warning(
            "video STT grant unavailable",
            extra={"component": "video", "failure_code": "unavailable"},
        )
