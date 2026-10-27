"""Real file service admission; no provider, database or storage network calls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.key_value import ServiceType
from service.services.files.application.file_saver_service import FileSaverService
from service.settings import config


class Cache:
    def __init__(self):
        self.values = {}

    async def set_json(self, namespace, identifier, payload, ttl_seconds):
        self.values[(namespace, identifier)] = payload

    async def get_json(self, namespace, identifier):
        return self.values.get((namespace, identifier))

    async def invalidate(self, namespace, identifier):
        self.values.pop((namespace, identifier), None)


class Repository:
    def __init__(self):
        self.rows = {}
        self.lost_ack = False
        self.operation_lock = asyncio.Lock()

    async def fetch_user_file_by_id(self, owner, file_id):
        row = self.rows.get(file_id)
        return row if row is not None and row.user_id == owner else None

    async def add_file_metadata(self, row):
        await asyncio.sleep(0)
        if row.id in self.rows:
            raise RuntimeError("fixture duplicate")
        self.rows[row.id] = row
        if self.lost_ack:
            raise OSError("PRIVATE_DATABASE_BODY")
        return row

    async def delete_file_metadata(self, *, user_id, file_id):
        row = await self.fetch_user_file_by_id(user_id, file_id)
        if row is not None:
            self.rows.pop(file_id)

    async def add_direct_file_metadata(self, row, verify_admission):
        async with self.operation_lock:
            if not await verify_admission():
                return None
            return await self.add_file_metadata(row)

    async def delete_owned_file_atomically(self, user_id, file_id, before_delete):
        async with self.operation_lock:
            row = await self.fetch_user_file_by_id(user_id, file_id)
            if row is None:
                return False
            await before_delete(row)
            await self.delete_file_metadata(user_id=user_id, file_id=file_id)
            return True


class Storage:
    def __init__(self):
        self.objects = {}
        self.commits = 0

    def build_file_path(self, folder, mode, name):
        return f"{folder}/{mode}/{name}"

    async def get_presigned_upload_url(self, **kwargs):
        return "https://fixture.example/upload"

    async def get_presigned_url(self, **kwargs):
        return "https://fixture.example/download"

    async def commit_presigned_upload(self, *, source_key, destination_key, max_bytes):
        self.commits += 1
        content = self.objects[source_key]
        if len(content) > max_bytes:
            raise ValueError("PRIVATE_STORAGE_BODY")
        self.objects[destination_key] = content

    async def delete_file(self, *, file_key):
        self.objects.pop(file_key, None)


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(config.file.settings, "allowed_extensions", [".png"])
    monkeypatch.setattr(config.file.settings, "max_file_size_byte", 8)
    repository, storage, cache = Repository(), Storage(), Cache()
    saver = FileSaverService(repository, "uploads", storage, upload_cache=cache)
    return saver, repository, storage, cache, uuid4()


@pytest.mark.asyncio
async def test_deleted_direct_upload_cannot_be_resurrected_by_callback(setup):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    storage.objects[offer["file_key"]] = b"initial"
    await saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    await saver.delete(owner, offer["file_id"])
    with pytest.raises(HTTPException) as missing:
        await saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    assert missing.value.status_code == 404
    assert not repository.rows
    assert storage.commits == 1
    assert await cache.get_json("file_upload_admission", str(offer["file_id"])) is None


@pytest.mark.asyncio
async def test_late_inflight_publication_cannot_resurrect_completed_delete(setup):
    saver, repository, storage, _cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    storage.objects[offer["file_key"]] = b"initial"
    real_copy = storage.commit_presigned_upload
    late_started, release_late = asyncio.Event(), asyncio.Event()
    slots = 0

    async def held_copy(**kwargs):
        nonlocal slots
        slots += 1
        slot = slots
        await real_copy(**kwargs)
        if slot == 1:
            await asyncio.wait_for(late_started.wait(), 2)
        else:
            late_started.set()
            await asyncio.wait_for(release_late.wait(), 2)

    storage.commit_presigned_upload = held_copy
    first = asyncio.create_task(
        saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    )
    late = asyncio.create_task(
        saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    )
    try:
        await asyncio.wait_for(first, 3)
        await saver.delete(owner, offer["file_id"])
        release_late.set()
        with pytest.raises(HTTPException) as revoked:
            await asyncio.wait_for(late, 3)
        assert revoked.value.status_code == 404
        assert not repository.rows
        assert set(storage.objects) == {offer["file_key"]}
    finally:
        release_late.set()
        await asyncio.gather(first, late, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_cache", "cache_transport"])
async def test_unconfirmed_direct_admission_revocation_keeps_library_source(setup, failure):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    storage.objects[offer["file_key"]] = b"initial"
    await saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    private = repository.rows[offer["file_id"]].file_name
    if failure == "missing_cache":
        saver.upload_cache = None
    else:
        cache.invalidate = AsyncMock(side_effect=OSError("PRIVATE_CACHE_BODY"))
    with pytest.raises(HTTPException) as failed:
        await saver.delete(owner, offer["file_id"])
    assert failed.value.status_code == 503
    assert failed.value.detail == "File is temporarily unavailable"
    assert private in storage.objects
    assert offer["file_id"] in repository.rows


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown", "owner", "key", "mode", "expired"])
async def test_callback_requires_exact_server_admission(setup, case):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    file_id, key, mode = offer["file_id"], offer["file_key"], ServiceType.CHAT
    if case == "unknown":
        file_id = uuid4()
    elif case == "owner":
        owner = uuid4()
    elif case == "key":
        key = "uploads/CHAT/other-owner.png"
    elif case == "mode":
        next(iter(cache.values.values()))["mode"] = "another-mode"
    else:
        next(iter(cache.values.values()))["expires_at"] = 0
    with pytest.raises(HTTPException) as error:
        await saver.finalize_upload(owner, mode, file_id, key)
    assert error.value.status_code == 404
    assert not repository.rows
    assert storage.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_replay_and_lost_ack_reuse_issued_id_and_private_copy(setup, lost_ack):
    saver, repository, storage, cache, owner = setup
    repository.lost_ack = lost_ack
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    key, file_id = offer["file_key"], offer["file_id"]
    storage.objects[key] = b"fixture"
    first = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    storage.objects[key] = b"changed"
    cache.values.clear()
    second = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    assert first == second
    assert first["file_id"] == file_id
    assert len(repository.rows) == 1
    row = repository.rows[file_id]
    assert row.original_name == "fixture.png"
    assert row.file_name != key
    assert storage.objects[row.file_name] == b"fixture"
    assert storage.commits == 1


@pytest.mark.asyncio
async def test_concurrent_callbacks_publish_one_row_and_clean_loser(setup):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    key, file_id = offer["file_key"], offer["file_id"]
    storage.objects[key] = b"fixture"
    results = await asyncio.gather(
        *[saver.finalize_upload(owner, ServiceType.CHAT, file_id, key) for _ in range(2)]
    )
    assert results[0] == results[1]
    assert len(repository.rows) == 1
    assert set(storage.objects) == {key, repository.rows[file_id].file_name}


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, b"too large source"])
async def test_incomplete_or_oversized_object_never_becomes_metadata(setup, content):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    if content is not None:
        storage.objects[offer["file_key"]] = content
    with pytest.raises(HTTPException) as error:
        await saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    assert error.value.status_code == 503
    assert error.value.detail == "Upload unavailable"
    assert not repository.rows


@pytest.mark.asyncio
async def test_initial_repository_failure_is_bounded_before_storage(setup, monkeypatch):
    saver, repository, storage, cache, owner = setup
    monkeypatch.setattr(
        repository, "fetch_user_file_by_id", AsyncMock(side_effect=OSError("PRIVATE_DB_BODY"))
    )
    with pytest.raises(HTTPException) as error:
        await saver.finalize_upload(owner, ServiceType.CHAT, uuid4(), "fixture-key")
    assert error.value.status_code == 503
    assert error.value.detail == "Upload unavailable"
    assert not repository.rows
    assert storage.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        None,
        "s3://fixture/object",
        "https://user:secret@fixture/",
        "https://fixture:invalid/",
        "https://fixture/\nprivate",
    ],
)
async def test_invalid_upload_capability_does_not_create_admission(setup, monkeypatch, url):
    saver, repository, storage, cache, owner = setup
    monkeypatch.setattr(storage, "get_presigned_upload_url", AsyncMock(return_value=url))
    with pytest.raises(HTTPException) as error:
        await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    assert error.value.status_code == 503
    assert error.value.detail == "Upload unavailable"
    assert not cache.values
    assert not repository.rows


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["issue", "callback"])
async def test_cache_failure_fails_closed(setup, monkeypatch, operation):
    saver, repository, storage, cache, owner = setup
    if operation == "issue":
        monkeypatch.setattr(cache, "set_json", AsyncMock(side_effect=OSError("PRIVATE_REDIS_BODY")))
        call = saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    else:
        offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
        monkeypatch.setattr(cache, "get_json", AsyncMock(side_effect=OSError("PRIVATE_REDIS_BODY")))
        call = saver.finalize_upload(owner, ServiceType.CHAT, offer["file_id"], offer["file_key"])
    with pytest.raises(HTTPException) as error:
        await call
    assert error.value.status_code == 503
    assert error.value.detail == "Upload unavailable"
    assert not repository.rows
    assert storage.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_commit_never_deletes_a_possible_owned_source(setup, monkeypatch, committed):
    saver, repository, storage, cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    key, file_id = offer["file_key"], offer["file_id"]
    storage.objects[key] = b"fixture"
    original_fetch = repository.fetch_user_file_by_id
    recovery_unavailable = False

    async def fetch(*args):
        if recovery_unavailable:
            raise OSError("PRIVATE_RECOVERY_BODY")
        return await original_fetch(*args)

    async def save(row):
        nonlocal recovery_unavailable
        if committed:
            repository.rows[row.id] = row
        recovery_unavailable = True
        raise OSError("PRIVATE_COMMIT_BODY")

    monkeypatch.setattr(repository, "fetch_user_file_by_id", fetch)
    monkeypatch.setattr(repository, "add_file_metadata", save)
    with pytest.raises(HTTPException) as error:
        await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    assert error.value.status_code == 503
    destinations = set(storage.objects) - {key}
    assert len(destinations) == 1
    if committed:
        assert repository.rows[file_id].file_name in destinations
        recovery_unavailable = False
        result = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
        assert result["file_id"] == file_id
        assert storage.commits == 1
    else:
        assert not repository.rows


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_ack", [False, True])
async def test_callback_recovery_retries_failed_scan_enqueue(setup, lost_ack):
    saver, repository, storage, cache, owner = setup
    repository.lost_ack = lost_ack
    push = AsyncMock(side_effect=[OSError("PRIVATE_QUEUE_BODY"), None])
    saver.message_bus = SimpleNamespace(push=push)
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    key, file_id = offer["file_key"], offer["file_id"]
    storage.objects[key] = b"fixture"
    first = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    second = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    third = await saver.finalize_upload(owner, ServiceType.CHAT, file_id, key)
    assert first == second == third
    assert len(repository.rows) == 1
    assert storage.commits == 1
    assert push.await_count == 2
    assert all(
        call.args == ("file:scan:queue", repository.rows[file_id].file_name)
        for call in push.await_args_list
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_state", ["absent", "committed", "unknown"])
async def test_repeated_cancel_drains_commit_recovery_before_deciding_cleanup(
    setup, monkeypatch, commit_state, caplog
):
    saver, repository, storage, _cache, owner = setup
    offer = await saver.presign_upload(owner, ServiceType.CHAT, "fixture.png")
    key, file_id = offer["file_key"], offer["file_id"]
    storage.objects[key] = b"fixture"
    saving, recovering, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_fetch = repository.fetch_user_file_by_id

    async def save(row):
        if commit_state == "committed":
            repository.rows[row.id] = row
        saving.set()
        await asyncio.Event().wait()

    async def fetch(*args):
        if saving.is_set():
            recovering.set()
            await release.wait()
            if commit_state == "unknown":
                raise OSError("PRIVATE_CANCEL_RECOVERY_BODY")
        return await original_fetch(*args)

    monkeypatch.setattr(repository, "add_file_metadata", save)
    monkeypatch.setattr(repository, "fetch_user_file_by_id", fetch)
    task = asyncio.create_task(saver.finalize_upload(owner, ServiceType.CHAT, file_id, key))
    try:
        await asyncio.wait_for(saving.wait(), 2)
        task.cancel()
        await asyncio.wait_for(recovering.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "repeated cancellation abandoned commit recovery"
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        destinations = set(storage.objects) - {key}
        if commit_state == "absent":
            assert not destinations
            assert not repository.rows
        else:
            assert len(destinations) == 1
            if commit_state == "committed":
                assert repository.rows[file_id].file_name in destinations
        assert "PRIVATE_CANCEL_RECOVERY_BODY" not in caplog.text
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
