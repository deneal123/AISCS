"""Accepted usage binds the canonical journal while holding its owned row lock."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.infrastructure.chat_worker.materialization.recovery import (
    MaterializationPlan,
    stage_materialization,
)
from service.services.chat.infrastructure.chat_worker.results.accepted import (
    accepted_turn,
    stage_accepted,
)
from service.services.chat.infrastructure.chat_worker.results.checkpoint import (
    PreparedCheckpointInvalid,
    store_prepared_turn,
)
from service.services.jobs.persistence.transitions import EXECUTION_KEY, USAGE_JOURNAL_KEY
from tests.test_worker_materialization_recovery import payload as plan_payload


def fixture():
    attempt = str(uuid4())
    usage = {
        "prompt_tokens": 20,
        "completion_tokens": 2,
        "total_tokens": 22,
        "per_call_usage": [
            {"provider": "gigachat", "model": "GigaChat-2", "prompt": 20, "completion": 2}
        ],
    }
    accepted = accepted_turn(
        job_id=str(uuid4()),
        owner_id=str(uuid4()),
        thread_id="fixture-thread",
        reply="fixture",
        model="GigaChat-2",
        usage=usage,
    )
    journal = {
        "schema_version": 1,
        "attempt_id": attempt,
        "revision": 2,
        "receipts": [
            {
                "receipt_id": "call",
                "provider": "gigachat",
                "model": "GigaChat-2",
                "kind": None,
                "prompt": 20,
                "completion": 2,
                "estimated": False,
            }
        ],
    }
    stored = {"thread_id": "fixture-thread", EXECUTION_KEY: attempt, USAGE_JOURNAL_KEY: journal}
    return accepted, {"status": ProcessingStatus.PROCESSING, "payload": stored}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bare", "materialization", "prepared"])
@pytest.mark.parametrize("fault", ["usage", "attempt", "corrupt", "foreign", "outage"])
async def test_stale_or_unverified_journal_cannot_be_accepted(mode, fault):
    accepted, row = fixture()
    if fault == "usage":
        row["payload"][USAGE_JOURNAL_KEY]["receipts"][0]["prompt"] += 1
    elif fault == "attempt":
        row["payload"][EXECUTION_KEY] = str(uuid4())
    elif fault == "corrupt":
        row["payload"][USAGE_JOURNAL_KEY] = {"PRIVATE_BODY": "bad"}
    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(return_value=None if fault == "foreign" else row),
        stage_accepted_turn=AsyncMock(return_value=True),
        stage_accepted_materialization=AsyncMock(return_value=True),
        stage_prepared_turn=AsyncMock(return_value=True),
    )
    if fault == "outage":
        repo.lock_prepared_turn.side_effect = RuntimeError("PRIVATE_BODY")
    db = AsyncMock()
    with pytest.raises(PreparedCheckpointInvalid) as caught:
        if mode == "bare":
            await stage_accepted(repo, db, accepted)
        elif mode == "prepared":
            await store_prepared_turn(repo, db, accepted)
        else:
            await stage_materialization(
                repo, db, accepted, MaterializationPlan.from_payload(plan_payload())
            )
    assert "PRIVATE_BODY" not in str(caught.value)
    repo.stage_accepted_turn.assert_not_awaited()
    repo.stage_accepted_materialization.assert_not_awaited()
    repo.stage_prepared_turn.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["bare", "materialization", "prepared"])
async def test_valid_acceptance_locks_and_validates_before_write_without_commit(mode):
    accepted, row = fixture()
    order = []

    async def lock(*args, **kwargs):
        order.append("lock")
        return deepcopy(row)

    async def write(*args, **kwargs):
        order.append("write")
        return True

    repo = SimpleNamespace(
        lock_prepared_turn=AsyncMock(side_effect=lock),
        stage_accepted_turn=AsyncMock(side_effect=write),
        stage_accepted_materialization=AsyncMock(side_effect=write),
        stage_prepared_turn=AsyncMock(side_effect=write),
    )
    db = AsyncMock()
    if mode == "bare":
        assert await stage_accepted(repo, db, accepted)
    elif mode == "prepared":
        assert await store_prepared_turn(repo, db, accepted)
    else:
        assert await stage_materialization(
            repo, db, accepted, MaterializationPlan.from_payload(plan_payload())
        )
    assert order == ["lock", "write"]
    db.commit.assert_not_awaited()
