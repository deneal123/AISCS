"""Owner-bound projection of chat uploads into the private agents run contract."""

from __future__ import annotations

import json
import mimetypes
import re
from typing import Any
from uuid import UUID

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CACHE_PREFIX = "chat:attachment-evidence:"
_CACHE_TTL_SEC = 60 * 60
_MAX_TEXT_CHARS = 400_000


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _cache_key(user_id: str, file_id: str) -> str:
    return f"{_CACHE_PREFIX}{user_id}:{file_id}"


async def cache_owner_attachment_evidence(
    redis: Any,
    *,
    user_id: str,
    upload_result: dict[str, Any],
    ttl_sec: int = _CACHE_TTL_SEC,
) -> None:
    """Keep server-extracted text private until the related chat run consumes it."""

    file_id = str(upload_result.get("file_id") or "").strip()
    digest = str(upload_result.get("content_sha256") or "").lower()
    content = str(upload_result.get("extracted_text") or "")[:_MAX_TEXT_CHARS]
    if redis is None or not file_id or not _SHA256.fullmatch(digest) or not content.strip():
        return
    value = {
        "file_id": file_id,
        "digest": digest,
        "name": str(upload_result.get("filename") or "material")[:1_000],
        "mime_type": str(upload_result.get("mime_type") or "application/octet-stream")[:120],
        "content": content,
    }
    await redis.set(
        _cache_key(str(user_id), file_id),
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        ex=max(30, min(int(ttl_sec), _CACHE_TTL_SEC)),
    )


async def _cached_evidence(redis: Any, user_id: str, file_id: str) -> dict[str, Any] | None:
    if redis is None:
        return None
    try:
        raw = await redis.get(_cache_key(user_id, file_id))
        parsed = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _durable_evidence(file_service: Any, row: Any) -> dict[str, Any] | None:
    """Re-extract one exact owned Library file when the short Redis cache has expired."""

    storage_key = str(getattr(row, "file_name", "") or "")
    if not storage_key:
        return None
    try:
        from service.services.chat.infrastructure.chat_worker.turn_context import decode_as_text
        from service.services.chat.infrastructure.media.opendataloader_parser import (
            OpenDataLoaderParser,
        )

        payload = await file_service.get_file_by_key(file_key=storage_key)
        if not payload:
            return None
        text = await OpenDataLoaderParser().parse(payload, storage_key)
        if not text:
            text = decode_as_text(payload)
    except Exception:
        return None
    content = str(text or "")[:_MAX_TEXT_CHARS]
    return {"content": content} if content.strip() else None


async def owner_checked_attachments(
    file_service: Any,
    *,
    user_id: str | None,
    file_ids: list[Any] | None,
    attachments: list[Any] | None,
    redis: Any = None,
) -> list[dict[str, Any]]:
    """Return content plus only DB-confirmed file identity; never a storage locator."""

    requested = {str(value) for value in (file_ids or []) if str(value or "").strip()}
    if not user_id or not requested:
        # Legacy callers still provide extracted content. Keep it usable, but do not
        # manufacture an owner binding or digest from browser-controlled metadata.
        return [
            {
                "kind": str(item.get("kind") or "document")[:32],
                "name": str(item.get("name") or item.get("filename") or "")[:1_000],
                "content": str(item.get("content") or ""),
            }
            for raw in (attachments or [])
            if (item := _mapping(raw)) and str(item.get("content") or "").strip()
        ]

    try:
        owner = UUID(str(user_id))
    except (TypeError, ValueError):
        return []

    by_id = {
        str(item.get("file_id")): item
        for raw in (attachments or [])
        if (item := _mapping(raw)) and str(item.get("file_id") or "") in requested
    }
    output: list[dict[str, Any]] = []
    for file_id in list(dict.fromkeys(str(value) for value in (file_ids or [])))[:8]:
        source = by_id.get(file_id)
        if source is None:
            continue
        try:
            row = await file_service.repository.fetch_user_file_by_id(owner, UUID(file_id))
        except (TypeError, ValueError):
            continue
        if row is None:
            continue
        digest = str(getattr(row, "content_sha256", "") or "").lower()
        claimed = str(source.get("digest") or source.get("sha256") or "").lower()
        if _SHA256.fullmatch(digest) and claimed and claimed != digest:
            # Same opaque ID with different bytes is never admitted as evidence.
            continue
        cached = await _cached_evidence(redis, str(user_id), file_id)
        if cached is not None and str(cached.get("digest") or "").lower() != digest:
            cached = None
        durable = await _durable_evidence(file_service, row) if cached is None else None
        # The browser may repeat safe identity fields so the UI survives reload, but
        # its extracted text is never evidence.  Only the server-side upload cache or
        # a fresh read of the exact owner-bound object may supply content.
        evidence = cached or durable or {}
        name = str(getattr(row, "original_name", "") or evidence.get("name") or "material")
        safe_name = name.replace("\\", "/").rsplit("/", 1)[-1][:1_000]
        inferred_mime = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        output.append(
            {
                "kind": "document",
                "file_id": file_id,
                "name": safe_name,
                "mime_type": str(evidence.get("mime_type") or inferred_mime)[:120],
                **({"digest": digest} if _SHA256.fullmatch(digest) else {}),
                "content": str(evidence.get("content") or "")[:_MAX_TEXT_CHARS],
            }
        )
    return output


__all__ = ["cache_owner_attachment_evidence", "owner_checked_attachments"]
