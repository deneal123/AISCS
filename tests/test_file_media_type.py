"""Streaming artifacts and legacy owned downloads need deterministic MIME headers."""

from io import BytesIO
from unittest.mock import Mock

import pytest

from service.infrastructure.storage.minio_file_storage import MinioFileStorage


def _storage():
    storage = MinioFileStorage.__new__(MinioFileStorage)
    storage._client = Mock()
    storage._client.presigned_get_object.return_value = "https://storage.example/owned"
    storage._bucket = "fixture"
    storage._retry_attempts = 1
    storage._retry_backoff = 0
    storage._presign_expiry = 3600
    storage._public_endpoint = ""
    return storage


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("opaque.PDF", "application/pdf"),
        ("opaque.zip", "application/zip"),
        ("opaque.md", "text/plain; charset=utf-8"),
        ("opaque.html", "application/octet-stream"),
    ],
)
async def test_storage_commits_a_safe_mime_type_for_bytes_and_streams(streaming, name, expected):
    storage = _storage()
    payload = b"synthetic fixture"
    if streaming:
        await storage.upload_file_stream(
            file_key="private/" + name, stream=BytesIO(payload), length=len(payload)
        )
    else:
        await storage.upload_file(file_key="private/" + name, file_data=payload)
    assert storage._client.put_object.call_args.kwargs.get("content_type") == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Документ.PDF", "application/pdf"),
        ("source.zip", "application/zip"),
        ("../summary.md", "text/plain; charset=utf-8"),
        ("untrusted.html", "application/octet-stream"),
    ],
)
async def test_owned_download_corrects_legacy_object_mime_without_object_rewrite(name, expected):
    storage = _storage()
    await storage.get_presigned_url(file_key="PRIVATE_STORAGE_KEY", download_name=name)
    headers = storage._client.presigned_get_object.call_args.kwargs["response_headers"]
    assert headers.get("response-content-type") == expected
    assert headers["response-content-disposition"].startswith("attachment;")
    assert "PRIVATE_STORAGE_KEY" not in str(headers)
    storage._client.put_object.assert_not_called()
