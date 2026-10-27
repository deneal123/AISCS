from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from service.models.key_value import ProcessingStatus, ServiceType
from service.services.chat.application.video_stt.execution import VideoSttFailure
from service.services.chat.application.video_stt.grants import (
    authorize_video_stt,
    mint_video_stt_grant,
)
from service.services.chat.presentation.routers import video_stt as route
from tests.test_video_stt_executor import PrivateRedis


@pytest_asyncio.fixture
async def binding(monkeypatch):
    monkeypatch.setenv("WORKSPACE_COORDINATION_SECRET", "private-test-secret")
    import time

    from service.services.chat.application.workspace_collaboration import mint_capability

    redis = PrivateRedis()
    owner = uuid4()
    job = SimpleNamespace(
        user_id=owner,
        id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "thread"},
    )
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    capability = mint_capability(
        "workspace", role="agent", actor_seed="actor", expires_at=time.time() + 600
    )
    token = await mint_video_stt_grant(
        redis,
        owner_id=str(owner),
        task_id="task",
        thread_id="thread",
        capability=capability,
        confirmed=True,
    )
    boundary = AsyncMock()
    monkeypatch.setattr(
        "service.services.chat.application.video_stt.grants.WorkspaceCollaborationStore",
        lambda *args, **kwargs: SimpleNamespace(agent_safe_boundary=boundary),
    )
    return redis, repository, job, token, boundary


@pytest.mark.asyncio
async def test_grant_bound_to_owned_processing_job(binding):
    redis, repository, job, token, boundary = binding
    authorized = await authorize_video_stt(redis, repository, token=token, duration_limit_sec=60)
    assert authorized.owner_id == str(job.user_id)
    assert authorized.job_id == str(job.id)
    assert authorized.language == "auto"
    repository.fetch_job_by_task_id.assert_awaited_once_with("task", job.user_id)
    boundary.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "thread", "terminal", "type"])
async def test_grant_does_not_authorize_other_or_terminal_job(binding, change):
    redis, repository, job, token, boundary = binding
    if change == "owner":
        job.user_id = uuid4()
    elif change == "thread":
        job.payload["thread_id"] = "other"
    elif change == "terminal":
        job.status = ProcessingStatus.SUCCESS
    else:
        job.type = "OTHER"
    with pytest.raises(VideoSttFailure, match="forbidden"):
        await authorize_video_stt(redis, repository, token=token, duration_limit_sec=60)
    boundary.assert_not_awaited()


@pytest.mark.asyncio
async def test_mint_requires_explicit_confirmation():
    with pytest.raises(VideoSttFailure, match="forbidden"):
        await mint_video_stt_grant(
            PrivateRedis(),
            owner_id=str(uuid4()),
            task_id="task",
            thread_id="thread",
            capability="unused",
            confirmed=False,
        )


def test_internal_route_without_grant_never_invokes_stt(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    monkeypatch.setattr(route, "get_optional_redis_client", lambda request: PrivateRedis())
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock())
    monkeypatch.setattr(
        route, "get_job_service", lambda request: SimpleNamespace(repository=repository)
    )
    whisper = AsyncMock()
    monkeypatch.setattr(route, "WhisperLocalTranscriber", whisper)
    response = TestClient(app).post(
        "/internal/video-stt/transcribe?duration_limit_sec=60", content=b"private audio"
    )
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "forbidden"}}
    repository.fetch_job_by_task_id.assert_not_awaited()
    whisper.assert_not_called()
    assert "/internal/video-stt/transcribe" not in app.openapi()["paths"]


def test_source_route_without_grant_never_fetches_media(monkeypatch):
    app = FastAPI()
    app.include_router(route.router)
    monkeypatch.setattr(route, "get_optional_redis_client", lambda request: PrivateRedis())
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock())
    monkeypatch.setattr(
        route, "get_job_service", lambda request: SimpleNamespace(repository=repository)
    )
    stream = AsyncMock()
    monkeypatch.setattr(route, "source_transcription_stream", stream)
    response = TestClient(app).post("/internal/video-stt/from-video", json={"url": "private-url"})
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "forbidden"}}
    repository.fetch_job_by_task_id.assert_not_awaited()
    stream.assert_not_called()
    assert "/internal/video-stt/from-video" not in app.openapi()["paths"]
