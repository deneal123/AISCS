"""Private checkpoint transport; no claims about runtime capture/head publication."""

import asyncio
import hashlib
import io
import json
import subprocess
import sys
import threading
import traceback
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob, IdeCheckpointError
from service.services.chat.domain.ide.runtime import RepositoryScope


def blob_for(body=b"binary\0\xff"):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    return CheckpointBlob(scope, uuid4(), hashlib.sha256(body).hexdigest(), len(body))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [b"", b"binary\0\xff", b"x" * (1024 * 1024 + 1)],
    ids=["empty", "binary", "spooled"],
)
async def test_persists_across_storage_instances_with_binary_integrity(tmp_path, body):
    blob = blob_for(body)
    source = io.BytesIO(body)
    await IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=len(body)).put(
        blob.scope, blob, source
    )
    assert not source.closed
    # A new adapter, no runtime container, no process-local cache of the contents.
    recovered = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=len(body))
    async with recovered.open(blob.scope, blob) as stream:
        assert stream.tell() == 0
        assert stream.read() == body
        assert stream._rolled is (len(body) > 1024 * 1024)
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["user_id", "thread_id", "repository_id"])
async def test_cross_owner_chat_repo_rejected_before_storage_io(changed):
    blob = blob_for()
    storage = AsyncMock()
    service = IdeCheckpointStorage(storage, max_bytes=100)
    foreign = replace(blob.scope, **{changed: uuid4()})
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_scope_forbidden$"):
        await service.put(foreign, blob, io.BytesIO(b"binary\0\xff"))
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_scope_forbidden$"):
        async with service.open(foreign, blob):
            pytest.fail("foreign blob was opened")
    storage.upload_file_stream.assert_not_awaited()
    storage.download_file_stream.assert_not_awaited()


@pytest.mark.parametrize("changed", ["user_id", "thread_id", "repository_id"])
def test_object_namespace_isolates_every_scope_component(changed):
    blob = blob_for()
    other = replace(blob, scope=replace(blob.scope, **{changed: uuid4()}))
    assert blob.key_for(blob.scope) != other.key_for(other.scope)
    assert str(blob.scope.user_id) not in repr(blob)
    assert blob.sha256 not in repr(blob)


@pytest.mark.parametrize(
    "changes",
    [
        {"size": -1},
        {"size": True},
        {"size": 2**63},
        {"size": 1.5},
        {"sha256": "a" * 63},
        {"sha256": "A" * 64},
        {"sha256": "../private"},
        {"sha256": None},
        {"checkpoint_id": "../private"},
        {"scope": None},
    ],
)
def test_invalid_private_reference_is_not_a_key(changes):
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_invalid$"):
        replace(blob_for(), **changes)


@pytest.mark.asyncio
async def test_quota_limit_rejects_reference_before_io():
    blob = blob_for()
    storage = AsyncMock()
    service = IdeCheckpointStorage(storage, max_bytes=blob.size - 1)
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_invalid$"):
        await service.put(blob.scope, blob, io.BytesIO(b"binary\0\xff"))
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_invalid$"):
        async with service.open(blob.scope, blob):
            pytest.fail("oversized reference")
    storage.upload_file_stream.assert_not_awaited()
    storage.download_file_stream.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"", b"x" * 8, b"x" * 9])
async def test_wrong_length_or_digest_never_uploads(body):
    blob = blob_for()
    storage = AsyncMock()
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_integrity_failed$"):
        await IdeCheckpointStorage(storage, max_bytes=100).put(blob.scope, blob, io.BytesIO(body))
    storage.upload_file_stream.assert_not_awaited()


@pytest.mark.asyncio
async def test_later_oversized_object_is_integrity_failure_not_partial_restore(tmp_path):
    blob = blob_for(b"original")
    storage = LocalFileStorage(tmp_path)
    await storage.upload_file(file_key=blob.key_for(blob.scope), file_data=b"original+extra")
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_integrity_failed$"):
        async with IdeCheckpointStorage(storage, max_bytes=100).open(blob.scope, blob):
            pytest.fail("truncated bytes exposed")


@pytest.mark.asyncio
async def test_mutable_caller_cannot_change_frozen_upload(tmp_path):
    body = b"frozen bytes"
    blob = blob_for(body)
    source = io.BytesIO(body)
    storage = LocalFileStorage(tmp_path)
    original = storage.upload_file_stream

    async def mutate(**kwargs):
        source.seek(0)
        source.write(b"changed body")
        return await original(**kwargs)

    storage.upload_file_stream = mutate
    service = IdeCheckpointStorage(storage, max_bytes=100)
    await service.put(blob.scope, blob, source)
    async with service.open(blob.scope, blob) as stream:
        assert stream.read() == body


@pytest.mark.asyncio
async def test_content_address_prevents_same_intent_different_body_overwrite(tmp_path):
    first = blob_for(b"original")
    second = replace(first, sha256=hashlib.sha256(b"modified").hexdigest())
    service = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=100)
    await asyncio.gather(
        service.put(first.scope, first, io.BytesIO(b"original")),
        service.put(second.scope, second, io.BytesIO(b"modified")),
    )
    assert first.key_for(first.scope) != second.key_for(second.scope)
    async with service.open(first.scope, first) as stream:
        assert stream.read() == b"original"
    async with service.open(second.scope, second) as stream:
        assert stream.read() == b"modified"


@pytest.mark.asyncio
async def test_readback_detects_same_size_corruption_before_upload_ack(tmp_path):
    blob = blob_for(b"original")
    storage = LocalFileStorage(tmp_path)
    original = storage.upload_file_stream

    async def corrupt(**kwargs):
        await original(**kwargs)
        await storage.upload_file(file_key=kwargs["file_key"], file_data=b"tampered")
        return "PRIVATE_PATH"

    storage.upload_file_stream = corrupt
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_integrity_failed$"):
        await IdeCheckpointStorage(storage, max_bytes=100).put(
            blob.scope, blob, io.BytesIO(b"original")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("copied", [True, None, 0])
async def test_download_receipt_cannot_substitute_for_actual_verified_body(copied):
    blob = blob_for()
    storage = AsyncMock()
    storage.download_file_stream.return_value = copied
    with pytest.raises(IdeCheckpointError, match="^ide_checkpoint_integrity_failed$"):
        async with IdeCheckpointStorage(storage, max_bytes=100).open(blob.scope, blob):
            pytest.fail("unverified bytes exposed")


@pytest.mark.asyncio
async def test_consumer_failure_is_not_relabelled_as_storage_failure(tmp_path):
    blob = blob_for(b"original")
    service = IdeCheckpointStorage(LocalFileStorage(tmp_path), max_bytes=100)
    await service.put(blob.scope, blob, io.BytesIO(b"original"))
    with pytest.raises(LookupError, match="consumer"):
        async with service.open(blob.scope, blob) as stream:
            raise LookupError("consumer")
    assert stream.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["put", "open"])
@pytest.mark.parametrize("failure", [OSError, asyncio.CancelledError])
async def test_failed_or_cancelled_transfer_does_not_delete_uncertain_object(operation, failure):
    blob = blob_for()
    storage = AsyncMock()
    storage.upload_file_stream.side_effect = failure("PRIVATE_KEY_URL_BODY")
    storage.download_file_stream.side_effect = failure("PRIVATE_KEY_URL_BODY")
    service = IdeCheckpointStorage(storage, max_bytes=100)
    expected = asyncio.CancelledError if failure is asyncio.CancelledError else IdeCheckpointError
    with pytest.raises(expected) as caught:
        if operation == "put":
            await service.put(blob.scope, blob, io.BytesIO(b"binary\0\xff"))
        else:
            async with service.open(blob.scope, blob):
                pytest.fail("failed download exposed")
    storage.delete_file.assert_not_awaited()
    if failure is not asyncio.CancelledError:
        assert "PRIVATE_KEY_URL_BODY" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "download"])
async def test_cancellation_cannot_close_staged_stream_while_native_io_owns_it(
    tmp_path, operation, monkeypatch
):
    blob = blob_for(b"original")
    storage = LocalFileStorage(tmp_path)
    service = IdeCheckpointStorage(storage, max_bytes=100)
    if operation == "download":
        await service.put(blob.scope, blob, io.BytesIO(b"original"))
    entered, release = threading.Event(), threading.Event()
    borrowed = []

    # Exercise the actual adapter's settled worker, not an AsyncMock that returns
    # before a background writer has stopped borrowing the internal spool.
    if operation == "upload":
        original = storage.upload_file_stream

        async def hold(**kwargs):
            staged = kwargs["stream"]
            borrowed.append(staged)
            read = staged.read

            def held_read(length):
                entered.set()
                assert release.wait(3)
                assert not staged.closed
                return read(length)

            monkeypatch.setattr(staged, "read", held_read)
            return await original(**kwargs)

        monkeypatch.setattr(storage, "upload_file_stream", hold)
    else:
        original = storage.download_file_stream

        async def hold(**kwargs):
            staged = kwargs["target"]
            borrowed.append(staged)
            write = staged.write

            def held_write(chunk):
                entered.set()
                assert release.wait(3)
                assert not staged.closed
                return write(chunk)

            monkeypatch.setattr(staged, "write", held_write)
            return await original(**kwargs)

        monkeypatch.setattr(storage, "download_file_stream", hold)

    async def transfer():
        if operation == "upload":
            await service.put(blob.scope, blob, io.BytesIO(b"original"))
        else:
            async with service.open(blob.scope, blob):
                pytest.fail("cancelled download exposed")

    task = asyncio.create_task(transfer())
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not borrowed[0].closed
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
    assert borrowed[0].closed


PROCESS_PROBE = """
import asyncio, hashlib, io, json, os, sys
from uuid import UUID
from service.infrastructure.ide.checkpoint_storage import IdeCheckpointStorage
from service.infrastructure.storage.local_file_storage import LocalFileStorage
from service.services.chat.domain.ide.checkpoints.blob import CheckpointBlob
from service.services.chat.domain.ide.runtime import RepositoryScope
args=json.load(sys.stdin)
body=b'synthetic-repository-bytes\\0\\xff'
scope=RepositoryScope(*(UUID(value) for value in args['scope']))
blob=CheckpointBlob(scope, UUID(args['id']), hashlib.sha256(body).hexdigest(),len(body))
async def run():
 storage=IdeCheckpointStorage(LocalFileStorage(args['root']),max_bytes=100)
 if args['operation']=='write':
  await storage.put(scope,blob,io.BytesIO(body))
 else:
  async with storage.open(scope,blob) as stream:
   assert stream.read()==body
try:
 asyncio.run(run())
 print(json.dumps({'status':'verified'}),flush=True)
 if args['operation']=='write': os._exit(23)
except BaseException:
 print(json.dumps({'status':'failed'}),flush=True)
 raise SystemExit(1)
"""


def test_local_verified_blob_is_readable_after_writer_process_exit(tmp_path):
    blob = blob_for()
    args = {
        "root": str(tmp_path),
        "scope": [
            str(blob.scope.thread_id),
            str(blob.scope.user_id),
            str(blob.scope.repository_id),
        ],
        "id": str(blob.checkpoint_id),
    }
    for operation, exit_code in (("write", 23), ("read", 0)):
        child = subprocess.run(
            [sys.executable, "-c", PROCESS_PROBE],
            input=json.dumps({**args, "operation": operation}),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert child.returncode == exit_code, "checkpoint_process_fixture_failed"
        assert json.loads(child.stdout) == {"status": "verified"}
