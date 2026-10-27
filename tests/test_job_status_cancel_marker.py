"""Generic status writes must preserve a durable control-plane cancellation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import NoResultFound

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.persistence.job_repository import JobRepository
from service.shared.repositories.exceptions import RepositoryNotFoundError


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ProcessingStatus.PROCESSING, ProcessingStatus.SUCCESS])
async def test_stale_payload_preserves_owned_cancel_marker(status, caplog):
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=status,
        payload={"thread_id": "thread", "reply": "updated"},
    )
    result = Mock()
    result.one.return_value = (
        ProcessingStatus.PROCESSING,
        {"_cancel_requested_v1": True, "private": "marker"},
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=result), merge=AsyncMock(), flush=AsyncMock()
    )
    repository = JobRepository(object())
    updated = await repository.update_job_status(job, session=session)
    assert updated.payload == {**job.payload, "_cancel_requested_v1": True}
    assert updated.status == status
    saved = session.merge.call_args.args[0]
    assert saved.user_id == job.user_id
    assert saved.payload["_cancel_requested_v1"] is True
    assert "private" not in saved.payload
    assert str(job.id) not in caplog.text
    query = str(session.execute.call_args.args[0])
    assert "FOR UPDATE" in query and "user_id" in query


@pytest.mark.asyncio
async def test_missing_owned_status_row_cannot_be_inserted_or_reassigned():
    result = Mock()
    result.one.side_effect = NoResultFound()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=result), merge=AsyncMock(), flush=AsyncMock()
    )
    repository = JobRepository(object())
    job = JobLogic(user_id=uuid4(), type=ServiceType.CHAT, status=ProcessingStatus.PROCESSING)
    with pytest.raises(RepositoryNotFoundError):
        await repository.update_job_status(job, session=session)
    session.merge.assert_not_awaited()
