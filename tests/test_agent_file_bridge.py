import base64
import uuid
from unittest.mock import Mock

import pytest

from service.infrastructure.agents_client import agent_file_bridge as bridge
from service.settings import config
from service.shared.repositories.exceptions import RepositoryIntegrityError


class _Saved:
    def __init__(self, file_url: str, file_key: str):
        self.file_id = uuid.uuid4()
        self.file_url = file_url
        self.file_key = file_key


class _FakeFileService:
    def __init__(self, fail_user_ids: set[uuid.UUID] | None = None):
        self.fail_user_ids = fail_user_ids or set()
        self.calls: list[uuid.UUID] = []

    async def save(self, *, user_id, mode, file_name, file_content):  # noqa: ANN001
        self.calls.append(user_id)
        if user_id in self.fail_user_ids:
            raise RepositoryIntegrityError("fk violation")
        return _Saved(file_url=f"/tmp/{file_name}", file_key=f"uploads/CHAT/{file_name}")


def test_collect_candidate_user_uuids_keeps_authenticated_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin_uuid)])

    primary = uuid.uuid4()
    candidates = bridge._collect_candidate_user_uuids(str(primary))

    assert candidates == [primary]


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_key", ["pptx_b64", "b64_json", "file_b64"])
async def test_authenticated_artifact_failure_never_changes_owner(monkeypatch, artifact_key):
    owner, admin = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin)])
    service = _FakeFileService(fail_user_ids={owner})
    artifact = {artifact_key: base64.b64encode(b"synthetic-content").decode()}
    if artifact_key == "file_b64":
        artifact["filename"] = "notes.md"
    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=service,
        user_id=str(owner),
        metadata={"_pending_artifacts": [artifact]},
        job_id="owner-bound-artifact",
    )
    assert service.calls == [owner]
    assert file_url is None
    assert not metadata.get("generated_files")
    assert "_pending_artifacts" not in metadata


@pytest.mark.asyncio
async def test_save_boundary_rejects_foreign_fallback_candidates(monkeypatch):
    owner, foreign = uuid.uuid4(), uuid.uuid4()
    service = _FakeFileService(fail_user_ids={owner})
    warning = Mock()
    monkeypatch.setattr(bridge.logger, "warning", warning)
    with pytest.raises(RepositoryIntegrityError, match="^Artifact persistence unavailable$"):
        await bridge._save_with_fallback(
            file_service=service,
            user_uuid_candidates=[foreign, owner],
            user_id=str(owner),
            filename="private-marker.md",
            content=b"private-marker",
            label="private-marker",
        )
    assert service.calls == [owner]
    assert warning.call_count == 1
    logged = repr(warning.call_args)
    assert "private-marker" not in logged
    assert str(owner) not in logged
    assert str(foreign) not in logged


@pytest.mark.asyncio
async def test_successful_artifact_keeps_exact_owner_with_admin_configured(monkeypatch):
    owner, admin = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin)])
    service = _FakeFileService()
    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=service,
        user_id=owner,
        metadata={
            "_pending_artifacts": [
                {
                    "file_b64": base64.b64encode(b"notes").decode(),
                    "filename": "notes.md",
                }
            ]
        },
        job_id="exact-owner",
    )
    assert service.calls == [owner]
    assert file_url and len(metadata["generated_files"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, "anonymous", "null", 123, bridge.ANON_USER_UUID])
@pytest.mark.parametrize("required", [False, True])
async def test_invalid_owner_never_persists_or_leaks_inline_artifacts(monkeypatch, owner, required):
    admin = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin)])
    service = _FakeFileService()
    encoded = base64.b64encode(b"private-inline-marker").decode()
    url, metadata = await bridge.persist_generated_artifacts(
        file_service=service,
        user_id=owner,
        metadata={
            "_pending_artifacts": [
                {"file_b64": encoded, "filename": "notes.md", "required": required}
            ],
            "b64_json": encoded,
            "pptx_b64": encoded,
            "safe_status": "retained",
        },
        job_id="invalid-owner",
    )
    assert service.calls == []
    assert url is None and not metadata.get("generated_files")
    assert encoded not in str(metadata)
    assert "_pending_artifacts" not in metadata
    assert metadata["safe_status"] == "retained"


@pytest.mark.asyncio
async def test_persist_generated_artifacts_rejects_missing_owner_even_with_admin_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin_uuid)])

    file_service = _FakeFileService(fail_user_ids={bridge.ANON_USER_UUID})
    pptx_b64 = base64.b64encode(b"pptx-binary").decode()

    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=file_service,
        user_id=None,
        metadata={"pptx_b64": pptx_b64, "filename": "demo"},
        job_id="job-123",
    )

    assert file_service.calls == []
    assert file_url is None
    assert not metadata.get("generated_files")
    assert "pptx_b64" not in metadata


@pytest.mark.asyncio
async def test_persist_generated_artifacts_persists_multiple_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A4: _pending_artifacts (мульти-интент) — КАЖДЫЙ артефакт персистится отдельно,
    в т.ч. две картинки одной модальности (раньше singular b64_json затирал одну)."""
    file_service = _FakeFileService()
    img1 = base64.b64encode(b"png-1").decode()
    img2 = base64.b64encode(b"png-2").decode()
    pptx = base64.b64encode(b"pptx-1").decode()

    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=file_service,
        user_id=str(uuid.uuid4()),
        metadata={
            "_pending_artifacts": [
                {"b64_json": img1},
                {"b64_json": img2},
                {"pptx_b64": pptx, "filename": "deck"},
            ]
        },
        job_id="job-multi",
    )

    gen = metadata.get("generated_files") or []
    assert len(gen) == 3, "не все артефакты персистнуты"
    assert [g["kind"] for g in gen] == ["image", "image", "presentation"]
    # имена картинок различаются (индекс) — в сторе не путаются
    assert gen[0]["filename"] != gen[1]["filename"]
    assert file_url == gen[0]["file_url"]
    assert "_pending_artifacts" not in metadata
    assert len(file_service.calls) == 3


@pytest.mark.asyncio
async def test_persist_generated_artifacts_keeps_response_stable_if_all_candidates_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin_uuid)])

    file_service = _FakeFileService(fail_user_ids={bridge.ANON_USER_UUID, admin_uuid})
    image_b64 = base64.b64encode(b"png-binary").decode()

    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=file_service,
        user_id="anonymous",
        metadata={"b64_json": image_b64},
        job_id="job-456",
    )

    assert file_url is None
    assert metadata.get("generated_files") is None
    assert "b64_json" not in metadata
