import base64
import uuid

import pytest

from service.infrastructure.agents_client import agent_file_bridge as bridge
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


def test_collect_candidate_user_uuids_includes_primary_and_admin_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(bridge.config.service, "admin_user_ids", [str(admin_uuid)])

    primary = uuid.uuid4()
    candidates = bridge._collect_candidate_user_uuids(str(primary))

    assert candidates[0] == primary
    assert admin_uuid in candidates


@pytest.mark.asyncio
async def test_persist_generated_artifacts_falls_back_to_admin_on_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(bridge.config.service, "admin_user_ids", [str(admin_uuid)])

    file_service = _FakeFileService(fail_user_ids={bridge.ANON_USER_UUID})
    pptx_b64 = base64.b64encode(b"pptx-binary").decode()

    file_url, metadata = await bridge.persist_generated_artifacts(
        file_service=file_service,
        user_id=None,
        metadata={"pptx_b64": pptx_b64, "filename": "demo"},
        job_id="job-123",
    )

    assert file_service.calls[0] == admin_uuid
    assert file_url is not None
    assert metadata.get("generated_files")
    assert metadata["generated_files"][0]["kind"] == "presentation"
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
    monkeypatch.setattr(bridge.config.service, "admin_user_ids", [str(admin_uuid)])

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
