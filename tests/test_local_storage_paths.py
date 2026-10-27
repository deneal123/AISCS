"""Local storage keys cannot read, overwrite or delete outside the configured root."""

from hashlib import sha256
from io import BytesIO

import pytest

from service.infrastructure.storage.local_file_storage import LocalFileStorage


async def operation(storage, name, key):
    if name == "upload":
        return await storage.upload_file(file_key=key, file_data=b"replacement")
    if name == "stream":
        return await storage.upload_file_stream(
            file_key=key, stream=BytesIO(b"replacement"), length=11
        )
    if name == "delete":
        return await storage.delete_file(file_key=key)
    if name == "head":
        return await storage.get_file_head(key, 8)
    if name == "metadata":
        return await storage.read_file_metadata(key)
    return await storage.get_file(key)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["upload", "stream", "delete", "head", "metadata", "get"])
async def test_parent_escape_preserves_external_sentinel(tmp_path, name):
    sentinel = tmp_path / "outside.txt"
    sentinel.write_bytes(b"private sentinel")
    storage = LocalFileStorage(tmp_path / "storage")
    with pytest.raises(ValueError, match="^storage_key_invalid$"):
        await operation(storage, name, "../outside.txt")
    assert sentinel.read_bytes() == b"private sentinel"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "",
        "/outside",
        "C:/outside",
        "C:outside",
        "a\\b",
        "a/../b",
        "a/./b",
        "a//b",
        "a/",
        "a:b",
        "a\x00b",
    ],
)
async def test_invalid_key_rejects_without_creating_files(tmp_path, key):
    storage = LocalFileStorage(tmp_path)
    with pytest.raises(ValueError, match="^storage_key_invalid$"):
        storage._path(key)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["upload", "stream", "delete", "head", "metadata", "get"])
async def test_symlink_parent_cannot_redirect_storage(tmp_path, name):
    root, outside = tmp_path / "storage", tmp_path / "outside"
    storage = LocalFileStorage(root)
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"private sentinel")
    try:
        (root / "redirect").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires platform privileges")
    with pytest.raises(ValueError, match="^storage_key_invalid$"):
        await operation(storage, name, "redirect/sentinel.txt")
    assert sentinel.read_bytes() == b"private sentinel"


@pytest.mark.asyncio
async def test_valid_nested_key_roundtrip(tmp_path):
    storage = LocalFileStorage(tmp_path)
    key = "owner/text/file.txt"
    await storage.upload_file(file_key=key, file_data=b"initial")
    assert await storage.get_file(key) == b"initial"
    await operation(storage, "stream", key)
    assert await storage.get_file_head(key, 4) == b"repl"
    assert await storage.read_file_metadata(key) == {
        "status": "ok",
        "size": 11,
        "sha256": sha256(b"replacement").hexdigest(),
    }
    await storage.delete_file(file_key=key)
    with pytest.raises(FileNotFoundError, match="^storage_file_missing$"):
        await storage.get_file(key)
