"""A disconnect during metadata persistence must resolve its storage ownership."""

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.models.key_value import ServiceType
from service.services.files.application import commit_resolution
from service.services.files.application import file_saver_service as saver_module
from service.services.files.application.commit_resolution import settle_cancelled_metadata
from service.services.files.application.file_saver_service import FileSaverService


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("resolution", ["committed", "absent", "unavailable"])
async def test_cancelled_metadata_resolves_exact_owner_key_without_success(
    streaming, resolution, caplog
):
    owner, intent = uuid4(), uuid4()
    payload = b"synthetic cancellation artifact"
    key = "fixture/CHAT/opaque.pdf"
    marker = "private-cancelled-metadata-marker"
    entered, release = asyncio.Event(), asyncio.Event()

    class Repository:
        row = None

        async def fetch_user_file_by_upload_intent(self, *_args):
            return None

        async def add_file_metadata(self, row):
            if resolution == "committed":
                row.id = uuid4()
                self.row = row
            raise asyncio.CancelledError(marker)

        async def fetch_user_file_by_name(self, user_id, file_key):
            assert user_id == owner and file_key == key
            entered.set()
            await release.wait()
            if resolution == "unavailable":
                raise OSError(marker)
            return self.row

    storage = SimpleNamespace(
        build_file_path=lambda *_: key,
        upload_file=AsyncMock(return_value="internal://fixture"),
        upload_file_stream=AsyncMock(return_value="internal://fixture"),
        delete_file=AsyncMock(),
    )
    saver = FileSaverService(Repository(), "fixture", storage)

    async def chunks():
        yield payload

    call = (
        saver.save_stream(
            owner,
            ServiceType.CHAT,
            "final.pdf",
            chunks(),
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_intent_id=intent,
        )
        if streaming
        else saver.save(owner, ServiceType.CHAT, "final.pdf", payload, upload_intent_id=intent)
    )
    task = asyncio.create_task(call)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()  # A second disconnect cannot abort commit resolution.
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        if resolution == "absent":
            storage.delete_file.assert_awaited_once_with(file_key=key)
        else:
            storage.delete_file.assert_not_awaited()
        assert marker not in caplog.text
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_compensation_has_deadline_and_bounded_diagnostic(monkeypatch):
    closed = asyncio.Event()
    warning = Mock()
    timeout = asyncio.timeout

    async def blocked_delete(*, file_key):
        assert file_key == "fixture/unique-key"
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    def deadline(seconds):
        assert seconds == 30
        return timeout(0.01)

    monkeypatch.setattr(asyncio, "timeout", deadline)
    monkeypatch.setattr(saver_module.logger, "warning", warning)
    storage = SimpleNamespace(delete_file=AsyncMock(side_effect=blocked_delete))
    saver = FileSaverService(SimpleNamespace(), "fixture", storage)
    await saver._delete_uploaded_object("fixture/unique-key")
    assert closed.is_set()
    storage.delete_file.assert_awaited_once_with(file_key="fixture/unique-key")
    warning.assert_called_once_with(
        "uploaded object cleanup failed",
        extra={"component": "file_storage", "failure_code": "cleanup"},
    )


@pytest.mark.asyncio
async def test_cancelled_metadata_settlement_has_bounded_deadline(monkeypatch):
    timeout = asyncio.timeout
    closed = asyncio.Event()
    warning = Mock()

    def deadline(seconds):
        assert seconds == 30
        return timeout(0.01)

    async def unresolved():
        try:
            await asyncio.Event().wait()
        finally:
            closed.set()

    monkeypatch.setattr(asyncio, "timeout", deadline)
    # Other suites reconfigure logging; assert the boundary call independently
    # of process-wide handlers/filters, not whether pytest happened to render it.
    monkeypatch.setattr(commit_resolution.logger, "warning", warning)
    await settle_cancelled_metadata(unresolved())
    assert closed.is_set()
    warning.assert_called_once_with(
        "cancelled file metadata unresolved",
        extra={"component": "file_library", "failure_code": "unavailable"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancelled", "owner_rejected"])
async def test_second_disconnect_cannot_interrupt_post_upload_compensation(failure):
    owner, intent = uuid4(), uuid4()
    payload = b"synthetic guarded publication"
    key = "fixture/CHAT/unique-attempt.pdf"
    entered, release, deleted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    repository = SimpleNamespace(
        fetch_user_file_by_upload_intent=AsyncMock(return_value=None),
        add_file_metadata=AsyncMock(),
    )

    async def delete_file(*, file_key):
        assert file_key == key
        entered.set()
        await release.wait()
        deleted.set()

    storage = SimpleNamespace(
        build_file_path=lambda *_: key,
        upload_file_stream=AsyncMock(return_value="internal://fixture"),
        delete_file=AsyncMock(side_effect=delete_file),
    )
    saver = FileSaverService(repository, "fixture", storage)
    checks = 0

    async def before_persist():
        nonlocal checks
        checks += 1
        if checks == 2:
            if failure == "owner_rejected":
                raise PermissionError("private-ownership-failure-marker")
            raise asyncio.CancelledError()

    async def chunks():
        yield payload

    task = asyncio.create_task(
        saver.save_stream(
            owner,
            ServiceType.CHAT,
            "final.pdf",
            chunks(),
            expected_size=len(payload),
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            upload_intent_id=intent,
            before_persist=before_persist,
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert deleted.is_set()
        storage.upload_file_stream.assert_awaited_once()
        storage.delete_file.assert_awaited_once_with(file_key=key)
        repository.add_file_metadata.assert_not_awaited()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
