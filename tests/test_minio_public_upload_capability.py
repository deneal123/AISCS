"""Browser upload capabilities use the same configured proxy as downloads."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from service.infrastructure.storage.minio_file_storage import MinioFileStorage


def adapter(url):
    storage = object.__new__(MinioFileStorage)
    storage.config = SimpleNamespace(endpoint="minio:9000")
    storage._public_endpoint = "https://files.example/proxy"
    storage._presign_expiry = 3600
    storage._bucket = "fixture"
    storage._client = SimpleNamespace(
        presigned_get_object=Mock(return_value=url), presigned_put_object=Mock(return_value=url)
    )
    return storage


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "download"])
@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_public_proxy_rewrite_preserves_signed_path_and_query(operation, scheme):
    suffix = "/fixture/opaque%20name.png?X-Amz-Signature=fixture%2Bsignature&X-Amz-Date=fixture"
    storage = adapter(f"{scheme}://minio:9000{suffix}")
    signer = (
        storage.get_presigned_upload_url if operation == "upload" else storage.get_presigned_url
    )
    result = await signer(file_key="opaque name.png", expiry_sec=17)
    assert result == f"https://files.example/proxy{suffix}"
    call = (
        storage._client.presigned_put_object
        if operation == "upload"
        else (storage._client.presigned_get_object)
    )
    assert call.call_args.kwargs["expires"].total_seconds() == 17


@pytest.mark.asyncio
async def test_upload_signer_failure_is_bounded():
    storage = adapter("unused")
    storage._client.presigned_put_object.side_effect = OSError("PRIVATE_SIGNER_BODY")
    with pytest.raises(RuntimeError, match="^storage_presign_failed$"):
        await storage.get_presigned_upload_url(file_key="owned-object")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "download"])
async def test_authority_prefix_is_not_an_internal_host_match(operation):
    url = "http://minio:9000.other.example/fixture/object?signature=fixture"
    storage = adapter(url)
    signer = (
        storage.get_presigned_upload_url if operation == "upload" else storage.get_presigned_url
    )
    assert await signer(file_key="fixture") == url


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "download"])
async def test_absent_public_endpoint_keeps_configured_storage_url(operation):
    url = "http://minio:9000/fixture/object?signature=fixture"
    storage = adapter(url)
    storage._public_endpoint = None
    signer = (
        storage.get_presigned_upload_url if operation == "upload" else storage.get_presigned_url
    )
    assert await signer(file_key="fixture") == url
