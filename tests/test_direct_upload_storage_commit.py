"""Storage publication freezes a verified object and drains cancelled copy I/O."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from service.infrastructure.storage.minio_file_storage import MinioFileStorage


def storage(client):
    adapter = object.__new__(MinioFileStorage)
    adapter._client = client
    adapter._bucket = "fixture"
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 8, 9])
async def test_copy_checks_size_and_uses_observed_etag(size):
    copies = []

    def copy(bucket, destination, source):
        assert bucket == "fixture"
        assert destination == "private-object"
        assert source.gen_copy_headers()["x-amz-copy-source-if-match"] == "fixture-etag"
        copies.append(destination)

    adapter = storage(
        SimpleNamespace(
            stat_object=lambda *_: SimpleNamespace(size=size, etag="fixture-etag"),
            copy_object=copy,
        )
    )
    if size > 8:
        with pytest.raises(RuntimeError, match="^storage_upload_commit_failed$"):
            await adapter.commit_presigned_upload(
                source_key="pending-object", destination_key="private-object", max_bytes=8
            )
        assert not copies
    else:
        await adapter.commit_presigned_upload(
            source_key="pending-object", destination_key="private-object", max_bytes=8
        )
        assert copies == ["private-object"]


@pytest.mark.asyncio
async def test_cancel_waits_for_copy_before_returning_to_compensation():
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    def copy(*_):
        entered.set()
        assert release.wait(5)
        completed.set()

    adapter = storage(
        SimpleNamespace(
            stat_object=lambda *_: SimpleNamespace(size=7, etag="fixture-etag"),
            copy_object=copy,
        )
    )
    task = asyncio.create_task(
        adapter.commit_presigned_upload(
            source_key="pending-object", destination_key="private-object", max_bytes=8
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert not completed.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    assert completed.is_set()
