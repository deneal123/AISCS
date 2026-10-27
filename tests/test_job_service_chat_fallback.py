import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from service.models.key_value import ProcessingStatus
from service.services.jobs.application.job_service import ANON_USER_UUID, JobService
from service.settings import JobConfig, config
from service.shared.repositories.exceptions import RepositoryIntegrityError


class _FakeJobRepository:
    def __init__(self, *, fail_user_ids: set[uuid.UUID] | None = None) -> None:
        self.fail_user_ids = fail_user_ids or set()
        self.seen_user_ids: list[uuid.UUID] = []

    async def create_job(self, new_job):  # noqa: ANN001
        self.seen_user_ids.append(new_job.user_id)
        if new_job.user_id in self.fail_user_ids:
            raise RepositoryIntegrityError("fk violation")
        return SimpleNamespace(id=uuid.uuid4(), status=ProcessingStatus.NEW)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, ANON_USER_UUID, "invalid"])
async def test_create_chat_job_rejects_non_owner_before_repository(
    monkeypatch: pytest.MonkeyPatch,
    owner,
) -> None:
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin_uuid)])

    repo = _FakeJobRepository(fail_user_ids={ANON_USER_UUID})
    service = JobService(JobConfig(), repo)

    with pytest.raises(HTTPException):
        await service.create_chat_job(user_id=owner, thread_id="thread-1", text="hello")

    assert repo.seen_user_ids == []


@pytest.mark.asyncio
async def test_create_chat_job_never_changes_owner_when_primary_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_uuid = uuid.uuid4()
    admin_uuid = uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin_uuid)])

    repo = _FakeJobRepository(fail_user_ids={user_uuid})
    service = JobService(JobConfig(), repo)

    with pytest.raises(HTTPException):
        await service.create_chat_job(user_id=user_uuid, thread_id="thread-2", text="hello")

    assert repo.seen_user_ids == [user_uuid]


@pytest.mark.asyncio
async def test_successful_chat_job_uses_exact_owner_with_admin_configured(monkeypatch):
    owner, admin = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(config.service, "admin_user_ids", [str(admin)])
    repository = _FakeJobRepository()
    response = await JobService(JobConfig(), repository).create_chat_job(owner, "thread", "text")
    assert response.status == ProcessingStatus.NEW
    assert repository.seen_user_ids == [owner]


@pytest.mark.asyncio
async def test_chat_job_failure_diagnostics_never_include_request_or_owner(monkeypatch):
    from service.services.jobs.application import job_service as module

    owner = uuid.uuid4()
    repository = _FakeJobRepository(fail_user_ids={owner})
    loggers = [Mock() for _ in range(3)]
    for level, logger in zip(("info", "warning", "error"), loggers, strict=True):
        monkeypatch.setattr(module.logger, level, logger)
    with pytest.raises(HTTPException):
        await JobService(JobConfig(), repository).create_chat_job(
            owner, "private-thread-marker", "private-request-marker"
        )
    output = repr([logger.call_args_list for logger in loggers])
    assert str(owner) not in output
    assert "private-thread-marker" not in output and "private-request-marker" not in output
