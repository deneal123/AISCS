"""Stage-only writes and their real finalizer preserve privacy and commit ordering."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from service.models.key_value import ProcessingStatus
from service.services.chat.domain.attachment_meta import user_message_meta
from service.services.chat.infrastructure.chat_worker.execution import run as runner
from service.services.chat.infrastructure.chat_worker.phases import RunPhase
from service.services.chat.infrastructure.chat_worker.results import persistence
from service.services.chat.infrastructure.chat_worker.results.document_publication import (
    document_origin_message_id,
)
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


def _request(**overrides):
    values = dict(
        job_id=str(uuid4()),
        thread_id=str(uuid4()),
        text="synthetic request",
        user_id=str(uuid4()),
        attachments=[{"name": "source.txt", "kind": "document", "file_id": str(uuid4())}],
    )
    return WorkerRunRequest(**{**values, **overrides})


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation", ["fresh", "offer", "question"])
async def test_stage_preserves_attachment_and_project_metadata_without_duplicate_user_turn(
    continuation,
):
    data = {
        "_document_context": {"project_id": str(uuid4())},
        "_ide_context": {"repository_id": str(uuid4())},
    }
    if continuation == "offer":
        data["confirmed_offer_id"] = "existing-offer"
    request = _request(
        session_data=data, question_resume=SimpleNamespace() if continuation == "question" else None
    )
    session = AsyncMock()
    hooks = SimpleNamespace(persist_chat_turn=AsyncMock(), update_job_status=AsyncMock())
    metadata = {"public": "value"}
    wakeup = await persistence.stage_turn_success(
        request,
        reply="answer",
        file_url=None,
        metadata=metadata,
        engine_env={},
        session=session,
        job_repo=object(),
        hooks=hooks,
    )
    write = hooks.persist_chat_turn.await_args.kwargs
    project = {
        "document_project": data["_document_context"]["project_id"],
        "ide_repository": data["_ide_context"]["repository_id"],
    }
    assert write["user_text"] == (request.text if continuation == "fresh" else "")
    assert write["user_metadata"] == (
        {**user_message_meta(request.attachments), **project} if continuation == "fresh" else {}
    )
    assert write["assistant_metadata"].items() >= project.items()
    assert metadata.items() >= project.items()
    assert not wakeup
    assert hooks.update_job_status.await_args.args[2] is ProcessingStatus.SUCCESS
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_delivery_is_staged_after_its_exact_origin_and_before_job_status(monkeypatch):
    request = _request()
    order = []
    descriptors = [{"private": "private-artifact-marker"}]
    metadata = {"_document_publications": descriptors, "awaiting_confirmation": True}
    hooks = SimpleNamespace(
        persist_chat_turn=AsyncMock(side_effect=lambda **kw: order.append("turn")),
        update_job_status=AsyncMock(side_effect=lambda *args: order.append("status")),
    )
    enqueue = AsyncMock(side_effect=lambda *args, **kw: order.append("outbox"))
    monkeypatch.setattr(persistence, "enqueue_document_intent", enqueue)
    session = AsyncMock()
    wakeup = await persistence.stage_turn_success(
        request,
        reply="answer",
        file_url=None,
        metadata=metadata,
        engine_env={"workspace_ref": {"workspace_id": "owned-workspace"}},
        session=session,
        job_repo=object(),
        hooks=hooks,
    )
    origin = document_origin_message_id(request.job_id)
    turn = hooks.persist_chat_turn.await_args.kwargs
    assert order == ["turn", "outbox", "status"]
    assert turn["assistant_message_id"] == origin
    assert turn["user_message_id"] == str(uuid5(NAMESPACE_URL, f"chat-offer:{request.job_id}"))
    assert enqueue.await_args.args == (session,)
    assert enqueue.await_args.kwargs == dict(
        user_id=request.user_id,
        thread_id=request.thread_id,
        workspace_id="owned-workspace",
        job_id=request.job_id,
        descriptors=descriptors,
        origin_message_id=origin,
    )
    assert wakeup is True
    assert "private-artifact-marker" not in str(metadata) + str(turn) + str(
        hooks.update_job_status.await_args
    )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "turn", "outbox", "status", "commit"])
async def test_real_finalizer_does_not_publish_or_wake_delivery_before_successful_commit(
    monkeypatch, fault
):
    events = []
    request = _request()
    metadata = {"_document_publications": [{"private": "private-artifact-marker"}]}
    state = MutableRunState(
        restored_result={
            "reply": "accepted answer",
            "metadata": metadata,
            "file_url": None,
            "pricing": {"is_complex": False, "tools": []},
            "elapsed_seconds": 0,
        },
        engine_env={"workspace_ref": {"workspace_id": "owned-workspace"}},
    )
    state.phase.advance(RunPhase.RESERVED)
    state.phase.advance(RunPhase.EXECUTING)

    async def step(name):
        events.append(name)
        if name == fault:
            raise RuntimeError("synthetic write failure")

    async def charge(**kwargs):
        await step("charge")
        return 7, kwargs["metadata"]

    hooks = SimpleNamespace(
        charge_and_describe=AsyncMock(side_effect=charge),
        persist_chat_turn=AsyncMock(),
        update_job_status=AsyncMock(),
        publish_committed_turn=AsyncMock(),
        extract_memory=AsyncMock(),
    )

    async def persist(**kwargs):
        await step("turn")

    async def status(*args):
        await step("status")

    async def publish(**kwargs):
        await step("publish")

    async def outbox(*args, **kwargs):
        await step("outbox")

    async def commit():
        await step("commit")

    hooks.persist_chat_turn.side_effect = persist
    hooks.update_job_status.side_effect = status
    hooks.publish_committed_turn.side_effect = publish
    session = AsyncMock()
    session.commit.side_effect = commit
    monkeypatch.setattr(persistence, "enqueue_document_intent", AsyncMock(side_effect=outbox))
    wakeup = Mock(side_effect=lambda: events.append("delivery"))
    monkeypatch.setattr(runner, "trigger_document_delivery", wakeup)
    call = runner._finalize_success(
        request,
        {"resolved_model": "synthetic"},
        None,
        config=object(),
        pg_connector=object(),
        redis_client=None,
        publisher=Mock(),
        job_repo=object(),
        file_service=object(),
        session=session,
        state=state,
        hooks=hooks,
        started_at=0,
    )
    expected = ["charge", "turn", "outbox", "status", "commit", "delivery", "publish"]
    if fault:
        with pytest.raises(RuntimeError, match="synthetic write failure"):
            await call
        assert events == expected[: expected.index(fault) + 1]
        assert state.phase.phase is RunPhase.CHARGED
        hooks.publish_committed_turn.assert_not_awaited()
        wakeup.assert_not_called()
    else:
        result = await call
        assert events == expected
        assert state.phase.phase is RunPhase.PERSISTED
        assert "private-artifact-marker" not in str(result)
    assert state.charged_credits == 7
