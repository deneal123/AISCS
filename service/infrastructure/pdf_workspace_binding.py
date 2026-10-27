"""Publish one observed PDF allocation without overwriting another binding."""

import json
import time

from service.infrastructure import workspace_client
from service.services.chat.domain.documents.preparation import PdfPreparationUnavailable


async def publish_pdf_binding(redis, ref: dict) -> dict:
    remaining = int(float(ref["expires_at"]) - time.time())
    if redis is None or remaining < 1:
        raise PdfPreparationUnavailable
    try:
        await workspace_client._redis_call(
            redis,
            "set",
            workspace_client._key(ref["thread_id"]),
            json.dumps(ref),
            nx=True,
            ex=remaining,
        )
    except Exception:
        raise PdfPreparationUnavailable from None
    return await current_pdf_binding(redis, ref)


async def current_pdf_binding(redis, ref: dict) -> dict:
    """A response or scaffold cannot adopt a concurrently replaced thread binding."""
    state, current = await workspace_client.read_binding_state(redis, ref["thread_id"])
    if (
        state != "ready"
        or not current
        or current.get("workspace_id") != ref["workspace_id"]
        or current.get("user_id") != ref["user_id"]
        or current.get("expires_at") != ref["expires_at"]
    ):
        raise PdfPreparationUnavailable
    return current
