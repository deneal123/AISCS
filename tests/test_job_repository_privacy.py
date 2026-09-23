from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.jobs.persistence.job_repository import JobRepository


@pytest.mark.asyncio
async def test_create_job_debug_log_does_not_include_payload() -> None:
    marker = "S22_PRIVATE_JOB_PAYLOAD"
    job = JobLogic(
        user_id=uuid4(),
        type=ServiceType.CHAT,
        status=ProcessingStatus.NEW,
        payload={"text": marker, "thread_id": str(uuid4())},
    )
    session = MagicMock()
    session.flush = AsyncMock()
    repository = JobRepository(MagicMock())

    with (
        patch.object(JobLogic, "model_validate", return_value=job),
        patch("service.services.jobs.persistence.job_repository.logger.debug") as debug_log,
    ):
        result = await repository.create_job(job, session=session)

    assert result is job
    template, *args = debug_log.call_args.args
    rendered = template % tuple(args)
    assert marker not in rendered
    assert "has_payload=True" in rendered
