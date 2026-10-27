"""Cancellation requested while queued outlives the Redis transport signal."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.chat.infrastructure.chat_worker.execution.cancellation import CancelledByUser
from service.services.chat.infrastructure.chat_worker.execution.job_state import (
    redelivery_short_circuit,
)
from service.services.jobs.application.job_application_service import JobApplicationService


@pytest.mark.asyncio
async def test_owned_chat_cancel_persists_intent_after_flag_ack():
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.NEW,
        payload={"thread_id": "thread"},
    )
    repository = SimpleNamespace(
        fetch_job_by_task_id=AsyncMock(return_value=job),
        request_chat_cancel=AsyncMock(return_value=True),
    )
    queue = Mock()
    service = JobApplicationService(
        SimpleNamespace(repository=repository, job_queue=queue),
        SimpleNamespace(set=AsyncMock(return_value=True)),
    )
    assert await service.cancel_task("task", user_id=owner) == {
        "task_id": "task",
        "cancelled": True,
    }
    repository.request_chat_cancel.assert_awaited_once_with(job.id, owner)
    queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
async def test_queued_cancel_stops_worker_without_redis_or_reservation():
    fetch = AsyncMock(
        return_value=(ProcessingStatus.NEW, {"thread_id": "thread", "_cancel_requested_v1": True})
    )
    with pytest.raises(CancelledByUser):
        await redelivery_short_circuit(object(), "job", object(), "owner", fetch_status=fetch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key",
    [
        "_accepted_turn_v1",
        "_prepared_turn_v1",
        "_materialization_plan_v1",
        "_usage_journal_v1",
        "_harness_task_v1",
    ],
)
async def test_cancel_intent_does_not_override_accepted_recovery(key):
    fetch = AsyncMock(
        return_value=(ProcessingStatus.PROCESSING, {"_cancel_requested_v1": True, key: {}})
    )
    assert (
        await redelivery_short_circuit(object(), "job", object(), "owner", fetch_status=fetch)
        is None
    )


@pytest.mark.asyncio
async def test_terminal_result_still_wins_over_cancel_marker():
    fetch = AsyncMock(
        return_value=(ProcessingStatus.SUCCESS, {"_cancel_requested_v1": True, "reply": "accepted"})
    )
    result = await redelivery_short_circuit(object(), "job", object(), "owner", fetch_status=fetch)
    assert result["reply"] == "accepted"


@pytest.mark.asyncio
async def test_cancel_checkpoint_outage_does_not_report_durable_success(caplog):
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.NEW,
        payload={"thread_id": "thread"},
    )
    repository = SimpleNamespace(
        fetch_job_by_task_id=AsyncMock(return_value=job),
        request_chat_cancel=AsyncMock(side_effect=RuntimeError("private-db-marker")),
    )
    queue = Mock()
    service = JobApplicationService(
        SimpleNamespace(repository=repository, job_queue=queue),
        SimpleNamespace(set=AsyncMock(return_value=True)),
    )
    with pytest.raises(HTTPException) as caught:
        await service.cancel_task("task", user_id=owner)
    assert caught.value.status_code == 503
    assert "private-db-marker" not in caplog.text + str(caught.value.detail)
    queue.cancel_task.assert_not_called()
