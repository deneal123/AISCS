"""A late usage checkpoint cannot invalidate an already accepted result."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.billing.usage.journal import (
    stage_usage_journal,
)
from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.jobs.persistence.job_repository import JobRepository
from service.services.jobs.persistence.transitions import EXECUTION_KEY, USAGE_JOURNAL_KEY
from tests.test_usage_journal import payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latch", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
@pytest.mark.parametrize("stored_journal", [True, False])
async def test_changed_journal_is_rejected_after_result_latch(latch, stored_journal):
    previous = payload()
    update = deepcopy(previous)
    update["revision"] = 2
    update["receipts"][0].update(prompt=19, completion=3, estimated=False)
    stored = {"thread_id": "thread", EXECUTION_KEY: update["attempt_id"], latch: {}}
    if stored_journal:
        stored[USAGE_JOURNAL_KEY] = previous
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": stored}
        ),
        stage_usage_journal=AsyncMock(return_value=True),
    )
    with pytest.raises(JobStateUnavailable, match="Usage checkpoint unavailable"):
        await stage_usage_journal(
            repo, AsyncMock(), job_id=uuid4(), owner_id=uuid4(), thread_id="thread", payload=update
        )
    repo.stage_usage_journal.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latch", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
async def test_identical_usage_ack_remains_idempotent_after_result_latch(latch):
    data = payload()
    stored = {
        "thread_id": "thread",
        EXECUTION_KEY: data["attempt_id"],
        latch: {},
        USAGE_JOURNAL_KEY: data,
    }
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(
            return_value={"status": ProcessingStatus.PROCESSING, "payload": stored}
        ),
        stage_usage_journal=AsyncMock(return_value=True),
    )
    assert not await stage_usage_journal(
        repo, AsyncMock(), job_id=uuid4(), owner_id=uuid4(), thread_id="thread", payload=data
    )
    repo.stage_usage_journal.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_update_also_rechecks_latches_in_sql():
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=0)
    repo = JobRepository(SimpleNamespace())
    assert not await repo.stage_usage_journal(
        uuid4(), uuid4(), "thread", str(uuid4()), "{}", session=db
    )
    statement = str(db.execute.await_args.args[0])
    for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"):
        assert "NOT (payload::jsonb ? '" + key + "')" in statement
