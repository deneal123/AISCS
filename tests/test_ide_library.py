import base64
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from service.infrastructure.ide.workspace import IdeWorkspaceClient
from service.infrastructure.storage.bounded_download import DownloadLimitExceeded
from service.models.key_value import ServiceType
from service.services.chat.application.ide.library import copy_library_file
from service.services.chat.application.workspace_collaboration import CollaborationConflict
from service.services.chat.domain.ide.edits import IdeEditError
from service.services.chat.domain.ide.runtime import RepositoryScope, WorkspaceBinding
from service.services.files.application.library_read import LibraryReadFailure, read_library_bytes


@pytest.mark.asyncio
async def test_owned_library_read_is_bounded_binary_and_digest_checked():
    raw = b"\x00\xffPK\x03\x04"
    row = SimpleNamespace(
        type=ServiceType.CHAT,
        file_name="private/key",
        content_sha256=hashlib.sha256(raw).hexdigest(),
    )
    repository = SimpleNamespace(fetch_user_file_by_id=AsyncMock(return_value=row))

    async def download(*, target, max_bytes, file_key):
        assert file_key == "private/key" and max_bytes == 20 * 1024 * 1024
        target.write(raw)
        return len(raw)

    storage = SimpleNamespace(download_file_stream=AsyncMock(side_effect=download))
    owner, file_id = uuid4(), uuid4()
    assert await read_library_bytes(repository, storage, owner, file_id) == raw
    repository.fetch_user_file_by_id.assert_awaited_once_with(owner, file_id)
    row.content_sha256 = "a" * 64
    with pytest.raises(LibraryReadFailure, match="integrity"):
        await read_library_bytes(repository, storage, owner, file_id)


@pytest.mark.asyncio
async def test_foreign_or_unavailable_library_never_uses_unbounded_fallback():
    repository = SimpleNamespace(fetch_user_file_by_id=AsyncMock(return_value=None))
    storage = SimpleNamespace(get_file=AsyncMock(), download_file_stream=AsyncMock())
    with pytest.raises(LibraryReadFailure, match="missing"):
        await read_library_bytes(repository, storage, uuid4(), uuid4())
    storage.download_file_stream.assert_not_awaited()
    repository.fetch_user_file_by_id.return_value = SimpleNamespace(
        type=ServiceType.CHAT, file_name="private", content_sha256=None
    )
    storage.download_file_stream.side_effect = DownloadLimitExceeded()
    with pytest.raises(LibraryReadFailure, match="limit"):
        await read_library_bytes(repository, storage, uuid4(), uuid4())
    storage.get_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_copy_uses_owned_generation_and_lease_before_source_read_and_rpc(monkeypatch):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    store = SimpleNamespace(preflight=AsyncMock(return_value={"fence": 9}))
    resolved = SimpleNamespace(binding=object())
    client = SimpleNamespace(write=AsyncMock(return_value={"written": True}))
    edits = SimpleNamespace(
        _context=AsyncMock(return_value=(resolved, "cap", store)),
        _current=AsyncMock(),
        runtime=SimpleNamespace(client=client),
    )
    files = SimpleNamespace(read_chat_library_bytes=AsyncMock(return_value=b"\0\xff"))
    monkeypatch.setattr(
        "service.services.chat.application.ide.library.verify_capability", lambda value: "verified"
    )
    args = dict(
        file_id=uuid4(),
        path="src/data.bin",
        generation="a" * 64,
        session="actor-session-012345",
        fence=9,
    )
    result = await copy_library_file(edits, files, scope, **args)
    assert result == dict(repository_id=str(scope.repository_id), generation="a" * 64, written=True)
    store.preflight.assert_awaited_once_with(
        "verified", mutation="write", path="src/data.bin", fence=9
    )
    files.read_chat_library_bytes.assert_awaited_once_with(scope.user_id, args["file_id"])
    assert client.write.await_args.kwargs["operation"] == "import"
    assert client.write.await_args.kwargs["expected_digest"] is None
    edits._context.side_effect = IdeEditError("ide_generation_changed")
    files.read_chat_library_bytes.reset_mock()
    with pytest.raises(IdeEditError, match="generation"):
        await copy_library_file(edits, files, scope, **args)
    files.read_chat_library_bytes.assert_not_awaited()


@pytest.mark.asyncio
async def test_library_storage_failure_is_not_dispatched_as_empty_or_partial_content():
    repository = SimpleNamespace(
        fetch_user_file_by_id=AsyncMock(
            return_value=SimpleNamespace(
                type=ServiceType.CHAT, file_name="private", content_sha256=None
            )
        )
    )
    for storage in [
        SimpleNamespace(),
        SimpleNamespace(download_file_stream=AsyncMock(side_effect=RuntimeError("PRIVATE"))),
        SimpleNamespace(download_file_stream=AsyncMock(return_value=1)),
    ]:
        with pytest.raises(LibraryReadFailure, match="^ide_library_unavailable$"):
            await read_library_bytes(repository, storage, uuid4(), uuid4())


@pytest.mark.asyncio
async def test_private_import_rpc_preserves_binary_integrity_and_never_retries():
    raw = b"\0\xffPK\x03\x04"
    calls = []
    expected = dict(
        written=True,
        path="data.zip",
        kind="file",
        size=len(raw),
        digest=hashlib.sha256(raw).hexdigest(),
    )

    async def handle(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/ide/import")
        assert base64.b64decode(body["content"], validate=True) == raw
        assert body["sha256"] == expected["digest"] and body["expected_digest"] is None
        calls.append(body)
        return httpx.Response(
            200, json=expected if len(calls) == 1 else {**expected, "size": len(raw) - 1}
        )

    settings = SimpleNamespace(
        workspace_enabled=True,
        workspace_url="http://workspace",
        workspace_api_key="private",
        workspace_timeout_sec=10,
        workspace_ttl_sec=600,
    )
    client = IdeWorkspaceClient(settings, transport=httpx.MockTransport(handle))
    binding = WorkspaceBinding("a" * 32, "123." + "b" * 64, int(time.time()) + 600)
    args = dict(
        path="data.zip",
        operation="import",
        content=raw,
        expected_digest=None,
        capability="signed-private",
        fence=2,
    )
    assert await client.write(uuid4(), binding, **args) == expected
    with pytest.raises(IdeEditError, match="ide_write_unconfirmed"):
        await client.write(uuid4(), binding, **args)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["lease", "generation", "source", "after_write"])
async def test_copy_does_not_publish_without_current_admission_or_hide_lost_generation(
    monkeypatch, phase
):
    scope = RepositoryScope(uuid4(), uuid4(), uuid4())
    store = SimpleNamespace(preflight=AsyncMock(return_value={"fence": 1}))
    resolved = SimpleNamespace(binding=object())
    writer = AsyncMock(return_value={"written": True})
    edits = SimpleNamespace(
        _context=AsyncMock(return_value=(resolved, "cap", store)),
        _current=AsyncMock(),
        runtime=SimpleNamespace(client=SimpleNamespace(write=writer)),
    )
    files = SimpleNamespace(read_chat_library_bytes=AsyncMock(return_value=b"data"))
    monkeypatch.setattr(
        "service.services.chat.application.ide.library.verify_capability", lambda value: "verified"
    )
    code = "ide_generation_changed"
    if phase == "lease":
        store.preflight.side_effect = CollaborationConflict("lease")
        code = "ide_edit_lease_changed"
    elif phase == "source":
        files.read_chat_library_bytes.side_effect = LibraryReadFailure()
        code = "ide_library_unavailable"
    elif phase == "after_write":
        edits._current.side_effect = [None, IdeEditError(code)]
    else:
        edits._current.side_effect = IdeEditError(code)
    with pytest.raises(IdeEditError, match=code):
        await copy_library_file(
            edits,
            files,
            scope,
            file_id=uuid4(),
            path="data.bin",
            generation="a" * 64,
            session="session-0123456789",
            fence=1,
        )
    assert writer.await_count == (1 if phase == "after_write" else 0)
    if phase == "lease":
        files.read_chat_library_bytes.assert_not_awaited()
