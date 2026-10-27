"""PDF consent does not skip ownership validation or credit reservation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents import context as documents
from service.services.chat.infrastructure.chat_worker.billing.reservation import prepare as worker
from service.services.chat.infrastructure.chat_worker.run_contracts import (
    MutableRunState,
    WorkerRunRequest,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "document,declined,approved", [(True, False, True), (True, True, False), (False, False, False)]
)
async def test_pdf_consent_still_reserves_and_honors_billing_rejection(
    monkeypatch, document, declined, approved
):
    target = {"path": "documents/paper", "expected_revision": "r1"}
    validated = {**target, "project_id": "owned", "tools_auto_approved": True}
    validate = AsyncMock(return_value=validated)
    monkeypatch.setattr(documents, "validate_document_context", validate)
    monkeypatch.setattr(worker, "create_session", Mock())
    monkeypatch.setattr(worker, "owner_checked_attachments", AsyncMock(return_value=[]))
    rejection = {"error_code": "insufficient_credits"}
    reserve = AsyncMock(return_value=(rejection, None, 0))
    hooks = SimpleNamespace(
        update_job_status=AsyncMock(),
        restore_history=AsyncMock(),
        reservation_context_chars=Mock(return_value=0),
        reserve_credits=reserve,
    )
    data = {"confirmation_decision": "decline"} if declined else {}
    if document:
        data["_document_context"] = target
    request = WorkerRunRequest(
        job_id="job", thread_id="thread", text="edit", user_id="owner", session_data=data
    )
    session = AsyncMock()
    _, result = await worker._reserve_run(
        request,
        config=SimpleNamespace(agents=SimpleNamespace(chat_history_messages_limit=8)),
        pg_connector=None,
        publisher=None,
        job_repo=None,
        session=session,
        state=MutableRunState(),
        hooks=hooks,
        redis_client=None,
        file_service=None,
    )
    assert result is rejection
    reserve.assert_awaited_once()
    assert reserve.call_args.kwargs["expensive_run_confirmed"] is approved
    assert "tools_auto_approved" not in repr(reserve.call_args.kwargs["confirmation_context"])
    if document:
        validate.assert_awaited_once_with(None, "thread", "owner", target)
        assert request.session_data["_document_context"] is validated
    else:
        validate.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_or_foreign_document_cannot_reach_reservation(monkeypatch):
    validate = AsyncMock(side_effect=HTTPException(status_code=409, detail="stale_document"))
    monkeypatch.setattr(documents, "validate_document_context", validate)
    reserve = AsyncMock()
    request = WorkerRunRequest(
        job_id="job",
        thread_id="thread",
        text="edit",
        user_id="owner",
        session_data={
            "_document_context": {"path": "documents/paper", "tools_auto_approved": True}
        },
    )
    with pytest.raises(HTTPException):
        await worker._reserve_run(
            request,
            config=None,
            pg_connector=None,
            publisher=None,
            job_repo=None,
            session=AsyncMock(),
            state=MutableRunState(),
            hooks=SimpleNamespace(reserve_credits=reserve),
            redis_client=None,
            file_service=None,
        )
    assert validate.call_args.args[-1] == {"path": "documents/paper"}
    reserve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("declined", [False, True])
async def test_validated_pdf_consent_reaches_video_stt_grant(monkeypatch, declined):
    from service.infrastructure import workspace_client
    from service.services.chat.infrastructure.chat_worker.billing import (
        video_grant as video_stt_grant,
    )
    from service.services.chat.infrastructure.chat_worker.engine_env import build_engine_env

    monkeypatch.setattr(
        workspace_client,
        "ensure_workspace",
        AsyncMock(
            return_value={
                "workspace_id": "w",
                "user_id": "owner",
                "thread_id": "thread",
            }
        ),
    )
    monkeypatch.setattr(workspace_client, "import_files", AsyncMock())
    grant = AsyncMock()
    monkeypatch.setattr(video_stt_grant, "attach_video_stt_grant", grant)
    target = {"path": "documents/paper", "project_id": "owned", "tools_auto_approved": True}
    env = await build_engine_env(
        None,
        "thread",
        "owner",
        session_data={
            "_document_context": target,
            "confirmation_decision": "decline" if declined else None,
        },
    )
    assert env["video_tool_enabled"] is (not declined)
    assert grant.call_args.kwargs["confirmed"] is (not declined)
    assert env["workspace_ref"]["document_context"] == target
