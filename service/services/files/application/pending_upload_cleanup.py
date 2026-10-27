"""Fail-closed, paginated retention of temporary direct-upload source objects."""

from datetime import UTC, datetime, timedelta
from typing import Any

from service.services.files.domain.pending_upload import PendingUploadObject, pending_identity

_PREFIX = "uploads/CHAT/pending/"
_CURSOR_NAMESPACE = "file_upload_cleanup"
_RETENTION = timedelta(days=1)


def _expired(item: PendingUploadObject, cutoff: datetime) -> bool:
    return (
        isinstance(item.modified_at, datetime)
        and item.modified_at.tzinfo is not None
        and item.modified_at <= cutoff
        and isinstance(item.etag, str)
        and bool(item.etag)
        and type(item.size) is int
        and item.size >= 0
    )


def _same_version(left: PendingUploadObject, right: PendingUploadObject) -> bool:
    # S3 ListObjects includes fractional seconds; HEAD Last-Modified is an HTTP
    # date with second precision. Keep exact key/ETag/size and independent age
    # checks: normalizing wire precision must not admit a replaced/recent source.
    return (
        left.key == right.key
        and left.etag == right.etag
        and left.size == right.size
        and left.modified_at.replace(microsecond=0) == right.modified_at.replace(microsecond=0)
    )


async def cleanup_pending_uploads(
    *, storage: Any, repository: Any, cache: Any, now: datetime | None = None
) -> dict[str, int | str]:
    """Process at most 128 sources; caller owns resource lifecycle, never private files."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("pending_cleanup_invalid")
    if cache is None or not callable(getattr(repository, "remove_unreferenced_pending", None)):
        return {"status": "unavailable", "scanned": 0, "deleted": 0, "skipped": 0, "failed": 0}
    cutoff = now - _RETENTION
    cursor_record = await cache.get_json(_CURSOR_NAMESPACE, "CHAT")
    cursor = cursor_record.get("cursor") if isinstance(cursor_record, dict) else None
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor.startswith(_PREFIX) or len(cursor) > 1024
    ):
        cursor = None
    page = await storage.pending_upload_page(_PREFIX, cursor, 128)
    counts: dict[str, int | str] = {
        "status": "success",
        "scanned": len(page.objects),
        "deleted": 0,
        "skipped": 0,
        "failed": 0,
    }
    for item in page.objects:
        identity = pending_identity(item.key, _PREFIX)
        if identity is None or not _expired(item, cutoff):
            counts["skipped"] = int(counts["skipped"]) + 1
            continue
        owner, file_id = identity

        async def remove(item: PendingUploadObject = item, file_id: Any = file_id) -> bool:
            if await cache.get_json("file_upload_admission", str(file_id)) is not None:
                return False
            current = await storage.pending_upload_stat(item.key)
            if current is None:
                return True  # Another sweep already removed it; storage absence acknowledged.
            if not _expired(current, cutoff) or not _same_version(current, item):
                return False
            await storage.delete_file(file_key=item.key)
            return True

        try:
            deleted = await repository.remove_unreferenced_pending(owner, file_id, item.key, remove)
        except Exception:
            counts["failed"] = int(counts["failed"]) + 1
            continue
        name = "deleted" if deleted else "skipped"
        counts[name] = int(counts[name]) + 1
    # Private progress avoids starving later keys behind a page of recent uploads.
    # A failed cursor write merely repeats an idempotent sweep, never broadens scope.
    await cache.set_json(
        _CURSOR_NAMESPACE, "CHAT", {"cursor": page.next_cursor}, ttl_seconds=7 * 86400
    )
    return counts
