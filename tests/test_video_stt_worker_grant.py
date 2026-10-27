import logging
from unittest.mock import AsyncMock

import pytest

from service.services.chat.infrastructure.chat_worker.billing import video_grant as worker


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirmed,task,capability", [(False, "task", "cap"), (True, None, "cap"), (True, "task", None)]
)
async def test_unconfirmed_or_unbound_worker_never_mints(monkeypatch, confirmed, task, capability):
    mint = AsyncMock()
    monkeypatch.setattr(worker, "mint_video_stt_grant", mint)
    ref = {"coordination_capability": capability}
    await worker.attach_video_stt_grant(
        None, ref, user_id="owner", thread_id="thread", task_id=task, confirmed=confirmed
    )
    mint.assert_not_awaited()
    assert "video_stt" not in ref


@pytest.mark.asyncio
async def test_confirmed_grant_is_private_job_resource(monkeypatch):
    mint = AsyncMock(return_value="private-token")
    monkeypatch.setattr(worker, "mint_video_stt_grant", mint)
    monkeypatch.setenv("WORKSPACE_COORDINATOR_URL", "http://backend:8000/")
    ref = {"coordination_capability": "private-capability"}
    await worker.attach_video_stt_grant(
        None, ref, user_id="owner", thread_id="thread", task_id="task", confirmed=True
    )
    assert ref["video_stt"] == {
        "grant": "private-token",
        "endpoint": "http://backend:8000/internal/video-stt/from-video",
    }
    mint.assert_awaited_once_with(
        None,
        owner_id="owner",
        thread_id="thread",
        task_id="task",
        capability="private-capability",
        confirmed=True,
    )


@pytest.mark.asyncio
async def test_grant_failure_is_local_and_redacted(monkeypatch, caplog):
    monkeypatch.setattr(
        worker, "mint_video_stt_grant", AsyncMock(side_effect=RuntimeError("secret marker"))
    )
    ref = {"coordination_capability": "private"}
    # Backend logging may disable propagation earlier in the full corpus.
    # Attach explicitly so this sentinel does not depend on test ordering.
    worker.logger.addHandler(caplog.handler)
    previous = worker.logger.level
    worker.logger.setLevel(logging.WARNING)
    try:
        await worker.attach_video_stt_grant(
            None, ref, user_id="owner", thread_id="thread", task_id="task", confirmed=True
        )
    finally:
        worker.logger.removeHandler(caplog.handler)
        worker.logger.setLevel(previous)
    assert "video_stt" not in ref
    assert "secret marker" not in caplog.text
    assert "unavailable" in caplog.text
