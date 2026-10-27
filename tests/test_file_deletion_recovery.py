"""Owned delete keeps a retryable reference until object deletion is acknowledged."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from minio.error import S3Error

from service.infrastructure.storage.minio_file_storage import MinioFileStorage
from service.services.files.application.file_saver_service import FileSaverService


def fixture_service():
    owner, file_id = uuid4(), uuid4()
    row = SimpleNamespace(id=file_id, user_id=owner, file_name="PRIVATE_OBJECT_KEY")
    service = FileSaverService.__new__(FileSaverService)
    service.repository = SimpleNamespace(
        fetch_user_file_by_id=AsyncMock(return_value=row), delete_file_metadata=AsyncMock()
    )
    service.storage = SimpleNamespace(delete_file=AsyncMock())
    return service, owner, file_id


@pytest.mark.asyncio
async def test_storage_failure_preserves_metadata_and_explicit_retry():
    service, owner, file_id = fixture_service()
    service.storage.delete_file.side_effect = [OSError("PRIVATE_STORAGE_BODY"), None]
    with pytest.raises(HTTPException) as failed:
        await service.delete(owner, file_id)
    assert failed.value.status_code == 503
    assert failed.value.detail == "File is temporarily unavailable"
    service.repository.delete_file_metadata.assert_not_awaited()
    await service.delete(owner, file_id)
    assert service.storage.delete_file.await_count == 2
    service.repository.delete_file_metadata.assert_awaited_once_with(user_id=owner, file_id=file_id)


@pytest.mark.asyncio
async def test_db_failure_follows_storage_ack_and_allows_explicit_retry():
    service, owner, file_id = fixture_service()
    order = []

    async def storage(**_kwargs):
        order.append("storage")

    async def metadata(**_kwargs):
        order.append("metadata")
        if len(order) == 2:
            raise OSError("PRIVATE_DB_BODY")

    service.storage.delete_file.side_effect = storage
    service.repository.delete_file_metadata.side_effect = metadata
    with pytest.raises(HTTPException) as failed:
        await service.delete(owner, file_id)
    assert failed.value.status_code == 503
    assert order == ["storage", "metadata"]
    await service.delete(owner, file_id)
    assert order == ["storage", "metadata", "storage", "metadata"]


@pytest.mark.asyncio
async def test_lookup_failure_is_bounded_before_any_mutation():
    service, owner, file_id = fixture_service()
    service.repository.fetch_user_file_by_id.side_effect = OSError("PRIVATE_DB_DSN")
    with pytest.raises(HTTPException) as failed:
        await service.delete(owner, file_id)
    assert failed.value.status_code == 503
    assert "PRIVATE" not in failed.value.detail
    service.storage.delete_file.assert_not_awaited()
    service.repository.delete_file_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_owned_row_does_not_delete_anything():
    service, owner, file_id = fixture_service()
    service.repository.fetch_user_file_by_id.return_value = None
    with pytest.raises(HTTPException) as failed:
        await service.delete(owner, file_id)
    assert failed.value.status_code == 404
    service.repository.fetch_user_file_by_id.assert_awaited_once_with(owner, file_id)
    service.storage.delete_file.assert_not_awaited()
    service.repository.delete_file_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancelled_storage_does_not_remove_metadata():
    service, owner, file_id = fixture_service()
    service.storage.delete_file.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.delete(owner, file_id)
    service.repository.delete_file_metadata.assert_not_awaited()


@pytest.mark.asyncio
async def test_minio_exhausted_delete_is_not_a_success_ack():
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "PRIVATE_BUCKET"
    storage._retry_attempts = 2
    storage._retry_backoff = 0
    storage._client = SimpleNamespace(remove_object=Mock(side_effect=OSError("PRIVATE_S3_BODY")))
    with pytest.raises(RuntimeError, match="^storage_delete_failed$"):
        await storage.delete_file(file_key="PRIVATE_OBJECT_KEY")
    assert storage._client.remove_object.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["NoSuchKey", "NoSuchBucket", "AccessDenied"])
async def test_minio_only_typed_missing_key_acknowledges_absence(code):
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._bucket = "PRIVATE_BUCKET"
    storage._retry_attempts = 1
    storage._retry_backoff = 0
    failure = S3Error(
        response=None,
        code=code,
        message="PRIVATE_S3_BODY",
        resource="PRIVATE_RESOURCE",
        request_id="request",
        host_id="host",
    )
    storage._client = SimpleNamespace(remove_object=Mock(side_effect=failure))
    if code == "NoSuchKey":
        await storage.delete_file(file_key="PRIVATE_OBJECT_KEY")
    else:
        with pytest.raises(RuntimeError, match="^storage_delete_failed$"):
            await storage.delete_file(file_key="PRIVATE_OBJECT_KEY")
    assert storage._client.remove_object.call_count == 1
