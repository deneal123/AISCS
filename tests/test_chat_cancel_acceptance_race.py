"""A stale control-plane read must never revoke worker-owned result recovery."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.application.job_application_service import JobApplicationService


@pytest.mark.asyncio
async def test_result_accepted_after_owner_read_cannot_be_revoked():
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "private-thread"},
    )
    queue = Mock()

    async def flag_written(*args, **kwargs):
        # Control-plane snapshot is now stale: the worker has accepted usage.
        job.payload["_accepted_turn_v1"] = {"private": "accepted-marker"}
        return True

    redis = SimpleNamespace(set=AsyncMock(side_effect=flag_written))
    repository = SimpleNamespace(
        fetch_job_by_task_id=AsyncMock(return_value=job),
        request_chat_cancel=AsyncMock(return_value=False),
    )
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue), redis)
    result = await service.cancel_task("task", user_id=owner)
    assert result == {"task_id": "task", "cancelled": False}
    assert job.payload["_accepted_turn_v1"] == {"private": "accepted-marker"}
    queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "exception", "negative_ack"])
async def test_chat_cancel_requires_acknowledged_cooperative_flag(mode, caplog):
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "private-thread"},
    )
    queue = Mock()
    redis = (
        None
        if mode == "missing"
        else SimpleNamespace(
            set=AsyncMock(
                return_value=False,
                side_effect=(
                    RuntimeError("private-redis-error-marker") if mode == "exception" else None
                ),
            )
        )
    )
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue), redis)
    with pytest.raises(HTTPException) as caught:
        await service.cancel_task("task", user_id=owner)
    assert caught.value.status_code == 503
    assert "private-redis-error-marker" not in caplog.text
    queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
async def test_simultaneous_completion_and_cancel_preserves_completed_result():
    from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
        run_with_cancel,
    )

    signal = asyncio.Event()

    class Redis:
        def get(self, key):
            return "1"

    async def work():
        await signal.wait()
        return {"reply": "accepted", "per_call_usage": [{"tokens": 1}]}

    signal.set()
    result = await run_with_cancel(
        work(), redis_client=Redis(), celery_task_id="task", poll_interval=0
    )
    assert result["reply"] == "accepted"
