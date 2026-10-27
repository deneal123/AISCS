"""Retention never broadens its namespace or treats unknown state as safe deletion."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.services.files.application.pending_upload_cleanup import cleanup_pending_uploads
from service.services.files.domain.pending_upload import (
    PendingUploadObject,
    PendingUploadPage,
    pending_identity,
)

NOW = datetime(2026, 10, 8, tzinfo=UTC)
PREFIX = "uploads/CHAT/pending/"


def item(age=timedelta(days=2)):
    owner, identifier = uuid4(), uuid4()
    return PendingUploadObject(f"{PREFIX}{owner.hex}/{identifier.hex}.png", NOW - age, "etag", 8)


def resources(objects):
    storage = SimpleNamespace(
        pending_upload_page=AsyncMock(return_value=PendingUploadPage(tuple(objects), None)),
        pending_upload_stat=AsyncMock(
            side_effect=lambda key: next(x for x in objects if x.key == key)
        ),
        delete_file=AsyncMock(),
    )
    cache = SimpleNamespace(get_json=AsyncMock(return_value=None), set_json=AsyncMock())

    async def guarded(owner, identifier, key, remove):
        return await remove()

    repository = SimpleNamespace(remove_unreferenced_pending=AsyncMock(side_effect=guarded))
    return storage, repository, cache


async def sweep(objects, **overrides):
    storage, repository, cache = resources(objects)
    result = await cleanup_pending_uploads(
        storage=overrides.get("storage", storage),
        repository=overrides.get("repository", repository),
        cache=overrides.get("cache", cache),
        now=NOW,
    )
    return result, storage, repository, cache


@pytest.mark.parametrize(
    "key",
    [
        "uploads/CHAT/private.png",
        "uploads/CHAT/pending/../file.png",
        f"{PREFIX}{uuid4()}/{uuid4()}.png",
        f"{PREFIX}{'0' * 32}/{uuid4().hex}.png",
        f"{PREFIX}{uuid4().hex}/{uuid4().hex}.png/extra",
        f"{PREFIX}{uuid4().hex}/{uuid4().hex}.PNG?token",
    ],
)
def test_pending_identity_rejects_noncanonical_keys(key):
    assert pending_identity(key, PREFIX) is None


@pytest.mark.parametrize("key", [None, False, 17, b"private-inventory-key"])
def test_pending_identity_rejects_non_string_inventory_keys(key):
    assert pending_identity(key, PREFIX) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["listing", "head"])
@pytest.mark.parametrize("size", [True, False])
async def test_boolean_size_never_establishes_safe_retention_deletion(stage, size):
    old = replace(item(), size=int(size))
    malformed = replace(old, size=size)
    listed = malformed if stage == "listing" else old
    storage, repository, cache = resources([listed])
    if stage == "head":
        storage.pending_upload_stat.side_effect = None
        storage.pending_upload_stat.return_value = malformed
    result = await cleanup_pending_uploads(
        storage=storage, repository=repository, cache=cache, now=NOW
    )
    assert result == {"status": "success", "scanned": 1, "deleted": 0, "skipped": 1, "failed": 0}
    storage.delete_file.assert_not_awaited()
    if stage == "listing":
        repository.remove_unreferenced_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_malformed_key_does_not_starve_following_valid_inventory_entry():
    old = item()
    malformed = replace(old, key=None)
    result, storage, _, _ = await sweep([malformed, old])
    assert result == {"status": "success", "scanned": 2, "deleted": 1, "skipped": 1, "failed": 0}
    storage.delete_file.assert_awaited_once_with(file_key=old.key)


@pytest.mark.asyncio
async def test_only_expired_canonical_sources_removed_and_cursor_saved():
    old, recent = item(), item(timedelta(minutes=30))
    result, storage, repository, cache = await sweep([old, recent])
    assert result == {"status": "success", "scanned": 2, "deleted": 1, "skipped": 1, "failed": 0}
    storage.delete_file.assert_awaited_once_with(file_key=old.key)
    repository.remove_unreferenced_pending.assert_awaited_once()
    cache.set_json.assert_awaited_once_with(
        "file_upload_cleanup", "CHAT", {"cursor": None}, ttl_seconds=7 * 86400
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "admission",
        "reference",
        "changed",
        "etag_changed",
        "size_changed",
        "second_changed",
        "database",
        "storage",
    ],
)
async def test_active_referenced_changed_or_unknown_objects_fail_closed(failure):
    old = item()
    storage, repository, cache = resources([old])
    if failure == "admission":
        cache.get_json.side_effect = [None, {"owner": "opaque"}]
    elif failure == "reference":
        repository.remove_unreferenced_pending.side_effect = None
        repository.remove_unreferenced_pending.return_value = False
    elif failure == "changed":
        storage.pending_upload_stat.side_effect = None
        storage.pending_upload_stat.return_value = PendingUploadObject(
            old.key, NOW, "new", old.size
        )
    elif failure in {"etag_changed", "size_changed", "second_changed"}:
        storage.pending_upload_stat.side_effect = None
        storage.pending_upload_stat.return_value = PendingUploadObject(
            old.key,
            old.modified_at
            + (timedelta(seconds=1) if failure == "second_changed" else timedelta()),
            "new" if failure == "etag_changed" else old.etag,
            old.size + int(failure == "size_changed"),
        )
    elif failure == "database":
        repository.remove_unreferenced_pending.side_effect = OSError("PRIVATE_DATABASE_BODY")
    else:
        storage.pending_upload_stat.side_effect = OSError("PRIVATE_STORAGE_BODY")
    result = await cleanup_pending_uploads(
        storage=storage, repository=repository, cache=cache, now=NOW
    )
    storage.delete_file.assert_not_awaited()
    assert result["deleted"] == 0
    assert result["failed"] == int(failure in {"database", "storage"})


@pytest.mark.asyncio
async def test_pagination_private_cursor_survives_recent_page():
    recent = item(timedelta(minutes=30))
    storage, repository, cache = resources([recent])
    cache.get_json.return_value = {"cursor": recent.key}
    storage.pending_upload_page.return_value = PendingUploadPage((recent,), recent.key)
    await cleanup_pending_uploads(storage=storage, repository=repository, cache=cache, now=NOW)
    storage.pending_upload_page.assert_awaited_once_with(PREFIX, recent.key, 128)
    cache.set_json.assert_awaited_once_with(
        "file_upload_cleanup", "CHAT", {"cursor": recent.key}, ttl_seconds=7 * 86400
    )


def test_cleanup_task_exposes_only_bounded_failure(monkeypatch, caplog):
    from service.services.files.infrastructure import maintenance

    monkeypatch.setattr(
        maintenance, "run_pending_cleanup", AsyncMock(side_effect=OSError("PRIVATE_BODY"))
    )
    assert maintenance.cleanup_pending_uploads_task.run() == {"status": "unavailable"}
    assert "PRIVATE_BODY" not in caplog.text


def test_cleanup_is_scheduled_on_maintenance_queue():
    from service.infrastructure.messaging.celery_app import celery_app

    name = "service.services.files.infrastructure.maintenance.cleanup_pending_uploads"
    assert celery_app.conf.task_routes[name]["queue"] == "maintenance"
    assert celery_app.conf.beat_schedule["cleanup-pending-uploads"] == {
        "task": name,
        "schedule": 3600.0,
    }


@pytest.mark.asyncio
async def test_inventory_fetches_one_bounded_page_with_private_resume_cursor():
    from service.infrastructure.storage.minio_file_storage import MinioFileStorage

    rows = [item() for _ in range(4)]
    adapter = MinioFileStorage.__new__(MinioFileStorage)
    adapter._bucket = "fixture"
    adapter._client = Mock(
        list_objects=Mock(
            return_value=iter(
                [
                    SimpleNamespace(
                        object_name=row.key,
                        last_modified=row.modified_at,
                        etag=row.etag,
                        size=row.size,
                    )
                    for row in rows
                ]
            )
        )
    )
    page = await adapter.pending_upload_page(PREFIX, None, 2)
    assert page.objects == tuple(rows[:2])
    assert page.next_cursor == rows[1].key
    adapter._client.list_objects.assert_called_once_with(
        "fixture", prefix=PREFIX, recursive=True, start_after=None
    )


@pytest.mark.asyncio
async def test_listing_and_head_timestamp_precision_do_not_block_same_object_cleanup():
    old = item()
    listed = PendingUploadObject(
        old.key, old.modified_at.replace(microsecond=123000), old.etag, old.size
    )
    storage, repository, cache = resources([listed])
    storage.pending_upload_stat.side_effect = None
    storage.pending_upload_stat.return_value = old
    result = await cleanup_pending_uploads(
        storage=storage, repository=repository, cache=cache, now=NOW
    )
    assert result["deleted"] == 1
    storage.delete_file.assert_awaited_once_with(file_key=old.key)


@pytest.mark.asyncio
async def test_cancellation_does_not_advance_retention_cursor_or_delete():
    import asyncio

    old = item()
    storage, repository, cache = resources([old])
    repository.remove_unreferenced_pending.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await cleanup_pending_uploads(storage=storage, repository=repository, cache=cache, now=NOW)
    cache.set_json.assert_not_awaited()
    storage.delete_file.assert_not_awaited()
