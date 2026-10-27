"""Wall-clock age cannot terminate a worker-owned chat or serialize its private payload."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.application.dto import StartJobRequest
from service.services.jobs.application.job_service import JobService
from service.settings import JobConfig


def repository_for(job):
    async def ongoing(*_args):
        return [job] if job.status in (ProcessingStatus.NEW, ProcessingStatus.PROCESSING) else []

    return Mock(
        fetch_jobs_by_user_id=AsyncMock(side_effect=ongoing),
        update_job_status=AsyncMock(return_value=job),
        create_job=AsyncMock(
            return_value=JobLogic(
                user_id=job.user_id,
                type=ServiceType.CHAT,
                status=ProcessingStatus.NEW,
            )
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "private_key",
    [
        "thread_id",
        "_accepted_turn_v1",
        "_prepared_turn_v1",
        "_materialization_plan_v1",
    ],
)
async def test_stale_worker_owned_chat_never_becomes_failure(private_key):
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        updated_at=datetime.now(UTC) - timedelta(days=1),
        payload={private_key: "private-checkpoint", "celery_task_id": "task"},
    )
    original = job.model_dump()
    repository = repository_for(job)
    with pytest.raises(HTTPException) as error:
        await JobService(JobConfig(), repository).create_job(
            job.user_id,
            StartJobRequest(file_id=uuid4(), type=ServiceType.CHAT),
        )
    assert error.value.status_code == 400
    assert job.model_dump() == original
    repository.update_job_status.assert_not_awaited()
    repository.create_job.assert_not_awaited()


@pytest.mark.asyncio
async def test_ongoing_job_diagnostics_do_not_serialize_private_payload(monkeypatch):
    from service.services.jobs.application import job_service as module

    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.NEW,
        payload={"thread_id": "private-thread", "text": "private-request-marker"},
    )
    loggers = [Mock() for _ in range(4)]
    for level, logger in zip(("info", "warning", "debug", "error"), loggers, strict=True):
        monkeypatch.setattr(module.logger, level, logger)
    with pytest.raises(HTTPException):
        await JobService(JobConfig(), repository_for(job)).create_job(
            job.user_id,
            StartJobRequest(file_id=uuid4(), type=ServiceType.CHAT),
        )
    output = repr([logger.call_args_list for logger in loggers])
    assert "private-request-marker" not in output and "private-thread" not in output
    assert str(job.user_id) not in output and str(job.id) not in output


@pytest.mark.asyncio
async def test_legacy_non_thread_job_retains_stale_cleanup():
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        updated_at=datetime.now(UTC) - timedelta(days=1),
        payload={"file_id": str(uuid4())},
    )
    repository = repository_for(job)
    result = await JobService(JobConfig(), repository).create_job(
        job.user_id,
        StartJobRequest(file_id=uuid4(), type=ServiceType.CHAT),
    )
    assert job.status == ProcessingStatus.FAILURE
    assert result.status == ProcessingStatus.NEW
    assert repository.update_job_status.await_count == 1
    assert repository.create_job.await_count == 1
