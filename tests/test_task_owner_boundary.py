"""Task identifiers alone must not authorize status access or cooperative cancellation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from service.main import app
from service.models.auth_models import AuthProfile
from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType, UserTypes
from service.services.jobs.application.job_application_service import JobApplicationService
from service.services.jobs.presentation.routers.jobs_api.jobs_api import get_job_application_service
from service.shared.security.auth_checker import check_auth


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/jobs/v1/task/known-task/status"),
        ("post", "/api/jobs/v1/task/known-task/cancel"),
    ],
)
def test_foreign_or_missing_task_is_denied_before_transport(method, path):
    owner = uuid4()
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=None))
    queue = Mock()
    queue.get_task_state.return_value = (
        True,
        True,
        {"private": "private-task-result-marker"},
        {},
        "SUCCESS",
    )
    queue.cancel_task.return_value = True
    redis = SimpleNamespace(set=AsyncMock())
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue), redis)
    app.dependency_overrides[check_auth] = lambda: AuthProfile(
        user_id=owner,
        fingerprint=None,
        type=UserTypes.REGISTERED,
    )
    app.dependency_overrides[get_job_application_service] = lambda: service
    try:
        response = getattr(TestClient(app), method)(path)
    finally:
        app.dependency_overrides.pop(check_auth, None)
        app.dependency_overrides.pop(get_job_application_service, None)
    assert response.status_code == 404
    assert "private-task-result-marker" not in response.text
    queue.get_task_state.assert_not_called()
    queue.cancel_task.assert_not_called()
    redis.set.assert_not_awaited()
    repository.fetch_job_by_task_id.assert_awaited_once_with("known-task", owner)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,status",
    [
        ({"_accepted_turn_v1": {"private": "marker"}}, ProcessingStatus.PROCESSING),
        ({"_prepared_turn_v1": {}}, ProcessingStatus.PROCESSING),
        ({}, ProcessingStatus.SUCCESS),
        ({}, ProcessingStatus.FAILURE),
    ],
)
async def test_cancel_preserves_accepted_or_terminal_owned_job(payload, status):
    owner = uuid4()
    job = JobLogic(user_id=owner, type=ServiceType.CHAT, status=status, payload=payload)
    queue = Mock()
    redis = SimpleNamespace(set=AsyncMock())
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue), redis)
    result = await service.cancel_task("task", user_id=owner)
    assert result == {"task_id": "task", "cancelled": False}
    assert job.payload == payload and job.status == status
    queue.cancel_task.assert_not_called()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_owned_chat_status_uses_sql_without_private_celery_payload():
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={"thread_id": "thread"},
    )
    queue = Mock()
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue))
    result = await service.get_task_status("task", user_id=owner)
    assert result.state == "STARTED" and result.result is None and result.status is None
    queue.get_task_state.assert_not_called()


@pytest.mark.asyncio
async def test_exhausted_harness_is_not_reported_as_running_or_exposed_as_private_payload():
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=ProcessingStatus.PROCESSING,
        payload={
            "thread_id": str(uuid4()),
            "_harness_transport_retry_v1": {
                "state": "blocked",
                "count": 3,
                "attempt_id": "private-attempt",
            },
            "_usage_journal_v1": {"private": "private-journal"},
        },
    )
    queue = Mock()
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue))
    result = await service.get_task_status("task", user_id=owner)
    assert result.state == "FAILURE" and "заблокировано" in result.status
    assert result.result is None and result.error
    assert "private" not in result.model_dump_json()
    assert job.status == ProcessingStatus.PROCESSING
    queue.get_task_state.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_task_status", "cancel_task"])
async def test_owner_lookup_failure_is_bounded_and_does_not_touch_transport(operation, caplog):
    repository = SimpleNamespace(
        fetch_job_by_task_id=AsyncMock(side_effect=RuntimeError("private-exception-marker"))
    )
    queue = Mock()
    redis = SimpleNamespace(set=AsyncMock())
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue), redis)
    with pytest.raises(HTTPException) as caught:
        await getattr(service, operation)("task", user_id=uuid4())
    assert caught.value.status_code == 503
    assert "private-exception-marker" not in str(caught.value.detail)
    assert "private-exception-marker" not in caplog.text
    queue.get_task_state.assert_not_called()
    queue.cancel_task.assert_not_called()
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["get_task_status", "cancel_task"])
async def test_repository_owner_mismatch_is_rejected_defensively(operation):
    job = JobLogic(user_id=uuid4(), type=ServiceType.CHAT, status=ProcessingStatus.PROCESSING)
    repository = SimpleNamespace(fetch_job_by_task_id=AsyncMock(return_value=job))
    queue = Mock()
    service = JobApplicationService(SimpleNamespace(repository=repository, job_queue=queue))
    with pytest.raises(HTTPException) as caught:
        await getattr(service, operation)("task", user_id=uuid4())
    assert caught.value.status_code == 404
    queue.get_task_state.assert_not_called()
    queue.cancel_task.assert_not_called()
