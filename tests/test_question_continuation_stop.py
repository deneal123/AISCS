"""Stop before consent/first execution has no worker to finish the child for it."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus, ServiceType
from service.services.chat.persistence.human_questions import cost as human_question_cost
from service.services.jobs.application.job_application_service import JobApplicationService
from service.services.jobs.persistence.question_cancellation import cancel_unstarted_question


def fixture(*, stopped=True, status=ProcessingStatus.NEW, extra=None):
    owner = uuid4()
    job = JobLogic(
        user_id=owner,
        type=ServiceType.CHAT,
        status=status,
        payload={
            "thread_id": str(uuid4()),
            "_human_question_parent_v1": {"question_id": str(uuid4())},
            **(extra or {}),
        },
    )
    repo = SimpleNamespace(
        fetch_job_by_task_id=AsyncMock(return_value=job),
        cancel_unstarted_question=AsyncMock(return_value=stopped),
        request_chat_cancel=AsyncMock(return_value=True),
    )
    queue = Mock()
    signal = AsyncMock(return_value=True)
    service = JobApplicationService(
        SimpleNamespace(repository=repo, job_queue=queue), SimpleNamespace(set=signal)
    )
    return SimpleNamespace(
        owner=owner, job=job, repo=repo, queue=queue, signal=signal, service=service
    )


@pytest.mark.asyncio
async def test_unstarted_question_stop_needs_no_cost_read_redis_or_broker():
    f = fixture()
    f.service._redis_client = None
    assert await f.service.cancel_task(str(f.job.id), user_id=f.owner) == {
        "task_id": str(f.job.id),
        "cancelled": True,
    }
    f.repo.cancel_unstarted_question.assert_awaited_once_with(f.job.id, f.owner)
    f.repo.request_chat_cancel.assert_not_awaited()
    f.queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
async def test_first_execution_race_falls_back_to_existing_cooperative_stop():
    f = fixture(stopped=False)
    assert (await f.service.cancel_task(str(f.job.id), user_id=f.owner))["cancelled"] is True
    f.signal.assert_awaited_once()
    f.repo.request_chat_cancel.assert_awaited_once_with(f.job.id, f.owner)
    f.queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_cancel_commit_does_not_claim_success_or_revoke_redelivery():
    f = fixture()
    f.repo.cancel_unstarted_question.side_effect = RuntimeError("private-db-error")
    with pytest.raises(HTTPException) as caught:
        await f.service.cancel_task(str(f.job.id), user_id=f.owner)
    assert caught.value.status_code == 503
    assert "private" not in str(caught.value.detail)
    f.signal.assert_not_awaited()
    f.queue.cancel_task.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fact", ["_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1"]
)
async def test_accepted_result_is_not_superseded_by_stop(fact):
    f = fixture(extra={fact: {}})
    assert (await f.service.cancel_task(str(f.job.id), user_id=f.owner))["cancelled"] is False
    f.repo.cancel_unstarted_question.assert_not_awaited()
    f.repo.request_chat_cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_processing_child_keeps_worker_owned_terminal_transition():
    f = fixture(status=ProcessingStatus.PROCESSING)
    assert (await f.service.cancel_task(str(f.job.id), user_id=f.owner))["cancelled"] is True
    f.repo.cancel_unstarted_question.assert_not_awaited()
    f.repo.request_chat_cancel.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [0, 1])
async def test_persistence_update_is_owned_question_bound_and_excludes_execution_facts(rows):
    job_id, owner = uuid4(), uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=rows)))
    assert await cancel_unstarted_question(session, job_id, owner) is bool(rows)
    statement, params = session.execute.call_args.args
    sql = str(statement)
    assert params == {"job": job_id, "owner": owner}
    for guard in (
        "j.user_id=:owner",
        "q.resume_job_id=j.id",
        "q.user_id=j.user_id",
        "q.state='accepted'",
        "j.status='NEW'",
        "_execution_attempt_v1",
        "_execution_accounting_v1",
        "_usage_journal_v1",
        "_accepted_turn_v1",
        "_prepared_turn_v1",
        "_materialization_plan_v1",
    ):
        assert guard in sql
    assert "status='FAILURE'" in sql and "'_cancel_requested_v1',true" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,execution_fact,expected",
    [
        ("pending", None, "cancelled"),
        ("accepted", None, "cancelled"),
        ("not_required", None, "cancelled"),
        ("declined", None, "declined"),
        *[
            ("accepted", key, "accepted")
            for key in (
                "_execution_attempt_v1",
                "_execution_accounting_v1",
                "_usage_journal_v1",
                "_accepted_turn_v1",
                "_prepared_turn_v1",
                "_materialization_plan_v1",
            )
        ],
    ],
)
async def test_cost_read_claims_never_started_only_without_execution_facts(
    monkeypatch, state, execution_fact, expected
):
    payload = {
        "_cancel_requested_v1": True,
        **({execution_fact: {}} if execution_fact else {}),
    }
    cost = SimpleNamespace(state=state, public=lambda **_kwargs: {"state": state})
    monkeypatch.setattr(
        human_question_cost,
        "_owned",
        AsyncMock(return_value=(None, None, {"now": 100, "payload": payload}, cost)),
    )
    view = await human_question_cost.HumanQuestionCostRepository.read.__wrapped__(
        None, None, uuid4(), session=object()
    )
    assert view["state"] == expected
