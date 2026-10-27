"""Chat terminal state belongs to the durable worker row, not Celery task success."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.application.job_service import JobService
from service.settings import JobConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("sql_status", [ProcessingStatus.PROCESSING, ProcessingStatus.SUCCESS])
@pytest.mark.parametrize("celery_success", [True, False])
async def test_chat_polling_keeps_sql_authority_and_private_checkpoint(sql_status, celery_success):
    payload = {
        "thread_id": "thread",
        "celery_task_id": "task",
        "_accepted_turn_v1": {"private": "checkpoint-marker"},
    }
    job = JobLogic(
        user_id=uuid4(), type=ServiceType.CHAT, status=ProcessingStatus.PROCESSING, payload=payload
    )
    original = deepcopy(job.model_dump())
    fresh = job.model_copy(deep=True, update={"status": sql_status})
    if sql_status == ProcessingStatus.SUCCESS:
        fresh.payload = {"thread_id": "thread", "reply": "accepted result"}
    repository = Mock()
    repository.fetch_job_by_id = AsyncMock(return_value=fresh)
    repository.update_job_status = AsyncMock()
    queue = Mock()
    queue.get_task_state.return_value = (
        True,
        celery_success,
        {"status": "error", "error_code": "unavailable"},
        {"provider_body": "private-provider-marker"},
        "SUCCESS" if celery_success else "FAILURE",
    )
    result = await JobService(JobConfig(), repository, queue)._sync_celery_status(job, "task")
    assert result.status == sql_status
    assert result.payload == fresh.payload
    assert job.model_dump() == original
    repository.fetch_job_by_id.assert_awaited_once_with(job.id, job.user_id)
    repository.update_job_status.assert_not_awaited()
    queue.get_task_state.assert_not_called()


@pytest.mark.asyncio
async def test_chat_polling_sql_outage_preserves_checkpoint_and_bounded_diagnostics(monkeypatch):
    from service.services.jobs.application import job_service as module

    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "private-thread", "_prepared_turn_v1": {"private": True}},
    )
    repository = Mock()
    repository.fetch_job_by_id = AsyncMock(side_effect=RuntimeError("private-db-error-marker"))
    repository.update_job_status = AsyncMock()
    warning = Mock()
    monkeypatch.setattr(module.logger, "warning", warning)
    result = await JobService(JobConfig(), repository, Mock())._sync_celery_status(job, "task")
    assert result == job
    repository.fetch_job_by_id.assert_awaited_once_with(job.id, job.user_id)
    repository.update_job_status.assert_not_awaited()
    assert warning.called
    assert "private-db-error-marker" not in repr(warning.call_args)
    assert "private-thread" not in repr(warning.call_args)


@pytest.mark.asyncio
async def test_chat_polling_missing_owned_row_is_not_a_celery_terminal():
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "thread"},
    )
    repository = Mock()
    repository.fetch_job_by_id = AsyncMock(return_value=None)
    repository.update_job_status = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await JobService(JobConfig(), repository, Mock())._sync_celery_status(job, "task")
    assert error.value.status_code == 404
    repository.update_job_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_result_polling_uses_column_task_id_and_fresh_owned_sql_status():
    owner = uuid4()
    first = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        celery_task_id="column-task",
        payload={"thread_id": "thread"},
    )
    final = first.model_copy(update={"status": ProcessingStatus.SUCCESS})
    repository = Mock()
    repository.fetch_job_by_id = AsyncMock(side_effect=[first, final])
    repository.update_job_status = AsyncMock()
    queue = Mock()
    result = await JobService(JobConfig(), repository, queue).fetch_job_result(owner, first.id)
    assert result.status == ProcessingStatus.SUCCESS and result.celery_task_id == "column-task"
    assert repository.fetch_job_by_id.await_count == 2
    assert all(
        call.args == (first.id, owner) for call in repository.fetch_job_by_id.await_args_list
    )
    queue.get_task_state.assert_not_called()
    repository.update_job_status.assert_not_awaited()
