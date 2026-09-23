"""S21: Work Hub accepts only durable Library files and explicit sandbox actions."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, UploadFile

from service.models.key_value import ServiceType
from service.services.chat.application.use_cases.upload_file_use_case import (
    AttachmentPersistenceError,
)
from service.services.chat.presentation.http import upload_api
from service.services.chat.presentation.routers.chat_api import workspace_api as api
from service.services.files.application.file_saver_service import (
    FileSaverService,
    UploadIntentConflict,
)


class _Profile:
    user_id = "7"


class _ChatService:
    async def ensure_thread_owner(self, thread_id: str, user_id: str) -> None:
        assert (thread_id, user_id) == ("thread-1", "7")


class _Store:
    async def snapshot(self, *, revision: str) -> dict:
        return {"issues": [], "leases": [], "activity": [], "control": {"state": "running"}}

    async def preflight(self, _capability, *, mutation: str, path: str, fence: int) -> dict:
        assert mutation == "import"
        assert path == "brief.txt"
        assert fence == 4
        return {"fence": fence}

    async def mark_stale(self, *, path: str, revision: str) -> None:
        assert (path, revision) == ("brief.txt", "r2")

    async def record_activity(self, action: str) -> None:
        assert action == "library_copied"


class _Files:
    def __init__(self) -> None:
        self.saved: list[dict] = []
        self.file_id = uuid4()

    async def list_chat_library_page(self, _user_id, *, limit: int, offset: int = 0) -> dict:
        return {"items": [], "next_offset": None}

    async def save(self, **kwargs):
        self.saved.append(kwargs)
        return SimpleNamespace(
            file_id=self.file_id,
            file_url="internal://stored",
            file_key="CHAT/opaque",
        )

    async def resolve_chat_library_import(self, _user_id, file_id, *, expiry_sec: int) -> dict:
        assert file_id == self.file_id
        assert expiry_sec <= 120
        return {"name": "brief.txt", "url": "internal://short-lived-source"}


@pytest.fixture
def ready_workspace(monkeypatch):
    ref = {
        "workspace_id": "workspace-opaque",
        "token": "never-public",
        "root": "/workspace",
        "expires_at": 4_000_000_000.0,
    }

    async def _view(_ref):
        return {"entries": [], "history": [], "revision": "r1", "recovered": False}

    async def _binding(_redis, _thread_id):
        return ref

    async def _binding_state(_redis, _thread_id):
        return "ready", ref

    monkeypatch.setattr(api.workspace_client, "read_binding", _binding)
    monkeypatch.setattr(api.workspace_client, "read_binding_state", _binding_state)
    monkeypatch.setattr(api.workspace_client, "view", _view)
    monkeypatch.setattr(api, "_collaboration", lambda _ref, _redis: _Store())
    monkeypatch.setattr(api, "_ui_capability", lambda _ref, _user_id: "opaque-capability")
    monkeypatch.setattr(api, "verify_capability", lambda _value: object())
    return ref


@pytest.mark.asyncio
async def test_activate_is_an_explicit_idempotent_action(ready_workspace, monkeypatch):
    calls: list[tuple[str, str]] = []

    async def _ensure(_redis, thread_id: str, user_id: str):
        calls.append((thread_id, user_id))
        return ready_workspace

    monkeypatch.setattr(api.workspace_client, "ensure_workspace_explicit", _ensure)
    files = _Files()

    first = await api.activate_work("thread-1", _Profile(), _ChatService(), files, None, 20)
    second = await api.activate_work("thread-1", _Profile(), _ChatService(), files, None, 20)

    assert calls == [("thread-1", "7"), ("thread-1", "7")]
    assert first["workspace"]["state"] == second["workspace"]["state"] == "ready"
    assert "token" not in str(first).lower()


@pytest.mark.asyncio
async def test_direct_work_upload_persists_library_then_returns_safe_import_outcome(
    ready_workspace, monkeypatch
):
    files = _Files()
    calls: list[dict] = []

    async def _import(ref, sources, *, expected_revision: str, fence: int):
        calls.append(
            {"ref": ref, "sources": sources, "revision": expected_revision, "fence": fence}
        )
        return {"imported": 1, "kept": 0, "revision": "r2"}

    monkeypatch.setattr(api.workspace_client, "import_into_workspace", _import)
    upload = UploadFile(filename="brief.txt", file=io.BytesIO(b"durable source"))

    result = await api.upload_file_to_workspace(
        "thread-1", upload, "r1", 4, _Profile(), _ChatService(), files, None
    )

    assert files.saved == [
        {
            "user_id": "7",
            "mode": ServiceType.CHAT,
            "file_name": "brief.txt",
            "file_content": b"durable source",
        }
    ]
    assert calls[0]["revision"] == "r1"
    assert calls[0]["fence"] == 4
    assert result == {
        "outcome": "imported",
        "workspace_status": "ready",
        "revision": "r2",
        "file": {
            "file_id": str(files.file_id),
            "name": "brief.txt",
            "file_type": "CHAT",
            "availability": "ready",
        },
    }
    assert "internal://" not in str(result)
    assert "capability" not in str(result)


@pytest.mark.asyncio
async def test_library_page_keeps_legacy_rows_without_disclosing_storage_key():
    file_id = UUID("11111111-1111-1111-1111-111111111111")

    class _Repository:
        async def fetch_user_files_metadata(self, _user_id, _mode, *, limit, offset):
            assert (limit, offset) == (3, 0)
            return [
                SimpleNamespace(
                    id=file_id,
                    original_name=None,
                    file_name="CHAT/secret-user-path/opaque-contract.PDF",
                )
            ]

    class _Storage:
        pass

    service = FileSaverService(_Repository(), "uploads", _Storage())
    page = await service.list_chat_library_page(uuid4(), limit=2)

    assert page == {
        "items": [
            {
                "file_id": str(file_id),
                "name": "Ранее загруженный файл 11111111.pdf",
                "file_type": "CHAT",
                "availability": "ready",
            }
        ],
        "next_cursor": None,
        "next_offset": None,
    }
    assert "secret-user-path" not in str(page)


def test_user_file_library_mode_matches_the_varchar_schema() -> None:
    """The initial migration defines ``profile.user_file.mode`` as varchar."""
    from sqlalchemy import String, select
    from sqlalchemy.dialects import postgresql

    from service.models.db.db_models import UserFile
    from service.models.key_value import ServiceType

    assert isinstance(UserFile.__table__.c.mode.type, String)
    statement = select(UserFile).where(UserFile.type == ServiceType.CHAT)
    assert "::service_type" not in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_file_save_records_original_name_before_a_chat_attachment_is_exposed():
    captured = []

    class _Repository:
        async def add_file_metadata(self, record):
            record.id = uuid4()
            captured.append(record)
            return record

    class _Storage:
        def build_file_path(self, *_parts):
            return "uploads/CHAT/opaque.md"

        async def upload_file(self, **_kwargs):
            return "internal://upload-result"

    service = FileSaverService(_Repository(), "uploads", _Storage())
    saved = await service.save(uuid4(), ServiceType.CHAT, "specification.md", b"body")

    assert captured[0].original_name == "specification.md"
    assert saved.file_id == captured[0].id


@pytest.mark.asyncio
async def test_library_import_source_includes_internal_integrity_digest(monkeypatch):
    file_id = uuid4()
    owner = uuid4()

    class _Repository:
        async def fetch_user_file_by_id(self, user_id, requested_id):
            assert (user_id, requested_id) == (owner, file_id)
            return SimpleNamespace(
                type=ServiceType.CHAT,
                original_name="publisher.zip",
                file_name="CHAT/private/opaque.zip",
                content_sha256="a" * 64,
            )

    service = FileSaverService(_Repository(), "uploads", object())

    async def presigned(*, file_key: str, expiry_sec: int):
        assert (file_key, expiry_sec) == ("CHAT/private/opaque.zip", 120)
        return "https://internal.example/opaque"

    monkeypatch.setattr(service, "get_presigned_url_by_key", presigned)

    result = await service.resolve_chat_library_import(owner, file_id, expiry_sec=120)

    assert result == {
        "name": "publisher.zip",
        "url": "https://internal.example/opaque",
        "sha256": "a" * 64,
    }


@pytest.mark.asyncio
async def test_chat_upload_fails_safely_when_a_durable_user_file_cannot_be_created(monkeypatch):
    class _UseCase:
        async def execute(self, **_kwargs):
            raise AttachmentPersistenceError("persistence unavailable")

    class _Billing:
        async def has_sufficient_credits(self, _user_id: str) -> bool:
            return True

    monkeypatch.setattr(upload_api, "get_upload_use_case", lambda _files: _UseCase())
    upload = UploadFile(filename="draft.txt", file=io.BytesIO(b"source"))
    chat_service = SimpleNamespace(file_service=object())

    with pytest.raises(HTTPException) as exc:
        await upload_api.upload_file_to_chat(
            _Profile(), upload, "thread-1", "local", "", chat_service, _Billing(), None
        )

    assert getattr(exc.value, "status_code", None) == 503
    assert "Не удалось сохранить файл" in str(getattr(exc.value, "detail", ""))


@pytest.mark.asyncio
async def test_library_cursor_is_stable_and_offset_remains_compatible():
    now = datetime(2026, 9, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(
            id=UUID(f"00000000-0000-0000-0000-00000000000{index}"),
            original_name=f"file-{index}.txt",
            file_name=f"CHAT/opaque-{index}.txt",
            created_at=now - timedelta(seconds=index),
        )
        for index in range(1, 4)
    ]

    class _Repository:
        calls: list[dict] = []

        async def fetch_user_files_metadata(self, _user_id, _mode, **options):
            self.calls.append(options)
            return rows if "before" not in options else rows[2:]

    repository = _Repository()
    service = FileSaverService(repository, "uploads", object())

    first = await service.list_chat_library_page(uuid4(), limit=2, offset=0)
    second = await service.list_chat_library_page(
        uuid4(), limit=2, offset=999, cursor=first["next_cursor"]
    )

    assert [item["name"] for item in first["items"]] == ["file-1.txt", "file-2.txt"]
    assert first["next_offset"] == 2
    assert second["items"][0]["name"] == "file-3.txt"
    assert repository.calls[1]["offset"] == 999  # ignored by the real repository with cursor
    assert repository.calls[1]["before"] == (rows[1].created_at, rows[1].id)


@pytest.mark.asyncio
async def test_upload_intent_reuses_one_user_file_and_rejects_different_content():
    user_id = uuid4()
    intent_id = uuid4()

    class _Repository:
        record = None

        async def fetch_user_file_by_upload_intent(self, _user_id, _intent_id):
            return self.record

        async def add_file_metadata(self, record):
            record.id = uuid4()
            self.record = record
            return record

    class _Storage:
        uploads = 0

        def build_file_path(self, *_parts):
            return "uploads/CHAT/opaque.txt"

        async def upload_file(self, **_kwargs):
            self.uploads += 1
            return "internal://stored"

    repository = _Repository()
    storage = _Storage()
    service = FileSaverService(repository, "uploads", storage)

    first = await service.save(
        user_id, ServiceType.CHAT, "brief.txt", b"same", upload_intent_id=intent_id
    )
    second = await service.save(
        user_id, ServiceType.CHAT, "brief.txt", b"same", upload_intent_id=intent_id
    )

    assert first.file_id == second.file_id
    assert second.reused is True
    assert storage.uploads == 1
    with pytest.raises(UploadIntentConflict):
        await service.save(
            user_id, ServiceType.CHAT, "brief.txt", b"different", upload_intent_id=intent_id
        )


@pytest.mark.asyncio
async def test_failed_metadata_write_compensates_the_uploaded_object():
    class _Repository:
        async def add_file_metadata(self, _record):
            raise RuntimeError("db unavailable")

    class _Storage:
        deleted: list[str] = []

        def build_file_path(self, *_parts):
            return "uploads/CHAT/orphan.txt"

        async def upload_file(self, **_kwargs):
            return "internal://stored"

        async def delete_file(self, *, file_key):
            self.deleted.append(file_key)

    storage = _Storage()
    service = FileSaverService(_Repository(), "uploads", storage)

    with pytest.raises(RuntimeError):
        await service.save(uuid4(), ServiceType.CHAT, "brief.txt", b"content")

    assert storage.deleted == ["uploads/CHAT/orphan.txt"]


@pytest.mark.asyncio
async def test_workspace_conflict_after_library_commit_returns_library_saved(
    ready_workspace, monkeypatch
):
    files = _Files()

    async def _conflict(*_args, **_kwargs):
        raise api.workspace_client.WorkspaceConflict("revision changed")

    monkeypatch.setattr(api.workspace_client, "import_into_workspace", _conflict)
    upload = UploadFile(filename="brief.txt", file=io.BytesIO(b"durable source"))

    result = await api.upload_file_to_workspace(
        "thread-1", upload, "r1", 4, _Profile(), _ChatService(), files, None
    )

    assert len(files.saved) == 1
    assert result["outcome"] == "library_saved"
    assert result["workspace_status"] == "conflict"
    assert result["file"]["file_id"] == str(files.file_id)
    assert "internal://" not in str(result)


@pytest.mark.asyncio
async def test_direct_upload_can_explicitly_create_workspace_and_owns_one_temporary_lease(
    monkeypatch,
):
    ref = {
        "workspace_id": "workspace-created",
        "root": "/workspace",
        "expires_at": 4_000_000_000.0,
    }
    calls: list[tuple] = []

    class _LeaseStore:
        async def acquire_lease(self, _capability, path):
            calls.append(("acquire", path))
            return SimpleNamespace(fence=9)

        async def release_lease(self, _capability, path, fence):
            calls.append(("release", path, fence))

        async def mark_stale(self, *, path, revision):
            calls.append(("stale", path, revision))

        async def record_activity(self, action):
            calls.append(("activity", action))

    async def _binding(_redis, _thread_id):
        return None

    async def _ensure(_redis, _thread_id, _user_id):
        calls.append(("activate",))
        return ref

    async def _view(_ref):
        return {"revision": "r-created"}

    async def _import(_ref, _sources, *, expected_revision, fence):
        calls.append(("import", expected_revision, fence))
        return {"imported": 1, "kept": 0, "revision": "r-imported"}

    monkeypatch.setattr(api.workspace_client, "read_binding", _binding)
    monkeypatch.setattr(api.workspace_client, "ensure_workspace_explicit", _ensure)
    monkeypatch.setattr(api.workspace_client, "view", _view)
    monkeypatch.setattr(api.workspace_client, "import_into_workspace", _import)
    monkeypatch.setattr(api, "_collaboration", lambda _ref, _redis: _LeaseStore())
    monkeypatch.setattr(api, "_ui_capability", lambda _ref, _user_id: "opaque-capability")
    monkeypatch.setattr(api, "verify_capability", lambda _value: object())
    files = _Files()
    intent_id = uuid4()

    result = await api.upload_file_to_workspace(
        "thread-1",
        UploadFile(filename="brief.txt", file=io.BytesIO(b"durable source")),
        "",
        0,
        _Profile(),
        _ChatService(),
        files,
        object(),
        intent_id,
    )

    assert result["outcome"] == "imported"
    assert files.saved[0]["upload_intent_id"] == intent_id
    assert calls == [
        ("activate",),
        ("acquire", "brief.txt"),
        ("import", "r-created", 9),
        ("stale", "brief.txt", "r-imported"),
        ("activity", "library_copied"),
        ("release", "brief.txt", 9),
    ]


@pytest.mark.asyncio
async def test_workspace_failure_does_not_hide_library(monkeypatch):
    ref = {
        "workspace_id": "workspace-opaque",
        "root": "/workspace",
        "expires_at": 4_000_000_000.0,
    }

    async def _binding_state(_redis, _thread_id):
        return "ready", ref

    async def _unavailable(_ref):
        raise api.workspace_client.WorkspaceUnavailable("sidecar timeout")

    monkeypatch.setattr(api.workspace_client, "read_binding_state", _binding_state)
    monkeypatch.setattr(api.workspace_client, "view", _unavailable)
    monkeypatch.setattr(api, "_collaboration", lambda _ref, _redis: _Store())
    files = _Files()

    async def _library(_user_id, *, limit, offset=0, cursor=""):
        return {
            "items": [{"file_id": "safe-id", "name": "safe.txt"}],
            "next_cursor": None,
            "next_offset": None,
        }

    files.list_chat_library_page = _library
    result = await api.work_snapshot("thread-1", _Profile(), _ChatService(), files, object(), 20)

    assert result["contract_version"] == 2
    assert result["workspace"]["state"] == "unavailable"
    assert result["library"]["state"] == "ready"
    assert result["library"]["items"][0]["name"] == "safe.txt"


@pytest.mark.asyncio
async def test_library_failure_does_not_hide_ready_workspace(ready_workspace):
    class _BrokenLibrary:
        async def list_chat_library_page(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    result = await api.work_snapshot(
        "thread-1", _Profile(), _ChatService(), _BrokenLibrary(), object(), 20
    )

    assert result["workspace"]["state"] == "ready"
    assert result["workspace"]["revision"] == "r1"
    assert result["library"]["state"] == "unavailable"


@pytest.mark.asyncio
async def test_redis_binding_failure_keeps_library_visible(monkeypatch):
    async def _binding_state(_redis, _thread_id):
        return "unavailable", None

    async def _library(_user_id, *, limit, offset=0, cursor=""):
        return {
            "items": [{"file_id": "safe-id", "name": "safe.txt"}],
            "next_cursor": None,
            "next_offset": None,
        }

    files = _Files()
    files.list_chat_library_page = _library
    monkeypatch.setattr(api.workspace_client, "read_binding_state", _binding_state)

    result = await api.work_snapshot("thread-1", _Profile(), _ChatService(), files, object(), 20)

    assert result["workspace"]["state"] == "unavailable"
    assert result["room"]["state"] == "unavailable"
    assert result["library"]["items"][0]["name"] == "safe.txt"


@pytest.mark.asyncio
async def test_proven_gone_workspace_expires_and_removes_only_its_binding(monkeypatch):
    ref = {
        "workspace_id": "workspace-gone",
        "root": "/workspace",
        "expires_at": 4_000_000_000.0,
    }
    forgotten: list[str] = []

    async def _binding_state(_redis, _thread_id):
        return "ready", ref

    async def _gone(_ref):
        raise api.workspace_client.WorkspaceGone("not found")

    async def _forget(_redis, thread_id):
        forgotten.append(thread_id)

    monkeypatch.setattr(api.workspace_client, "read_binding_state", _binding_state)
    monkeypatch.setattr(api.workspace_client, "view", _gone)
    monkeypatch.setattr(api.workspace_client, "forget_binding", _forget)

    result = await api.work_snapshot("thread-1", _Profile(), _ChatService(), _Files(), object(), 20)

    assert result["workspace"]["state"] == "expired"
    assert result["room"]["state"] == "expired"
    assert forgotten == ["thread-1"]
