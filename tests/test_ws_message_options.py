"""WS preparation preserves canonical options without owning identity or dispatch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.services.chat.application.use_cases.ws_message import handler
from service.services.chat.application.use_cases.ws_message.admission import WsAdmission, WsRoute
from service.services.chat.application.use_cases.ws_message.options import WsMessageOptions
from service.services.chat.domain.confirmation.offer import ConfirmationOfferAnchor


def anchor(**updates):
    values = dict(
        offer_id="owned-offer",
        thread_id="owned-thread",
        user_id=str(uuid4()),
        source_message_id=str(uuid4()),
        text="PRIVATE_SERVER_TEXT",
        selected_model="server-model",
        route_override="pdf_gen",
        resolved_category="pdf_gen",
        input_type="text",
        attachments=({"content": "PRIVATE_SERVER_ATTACHMENT"},),
        file_ids=("server-file",),
        continuation=dict(
            planning=False,
            multi_intent=True,
            persona_ids=["engineer"],
            memory_enabled=False,
            file_context="PRIVATE_SERVER_CONTEXT",
        ),
    )
    return ConfirmationOfferAnchor(**{**values, **updates})


def parse(msg, server=None, decision="accept"):
    return WsMessageOptions.from_message(
        msg, anchor=server, offer_id=server.offer_id if server else "", decision=decision
    )


@pytest.mark.parametrize("flag,expected", [(None, None), (False, False), (True, True)])
def test_fresh_tristate_defaults_and_closed_worker_projection(flag, expected):
    msg = dict(
        id="message",
        text="task",
        model="manual",
        input_type="text",
        web_search=True,
        file_context="file text",
        attachments=[{"file_id": "file"}],
        file_ids=["file"],
        memory_enabled=False,
        ldr_model="ldr",
        ldr_strategy="strategy",
        multi_intent=flag,
        planning=flag,
        persona_ids=["engineer", "", "  ", 2],
        detach_files=True,
        watch_video=True,
        confirm_expensive_run=True,
        user_id="forged-owner",
        job_id="forged-job",
        queue="forged-queue",
        session_data={"_ide_context": {"repository_id": "forged"}, "_routing_usage": "forged"},
    )
    options = parse(msg)
    admission = WsAdmission(
        WsRoute("resolved", "text", "general", False, False, "general", {"prompt": 7}),
        {"project_id": "owned-document"},
        None,
    )
    prepared = options.after_admission(admission, anchor=None, decision="accept")
    payload = prepared.worker_options("owned-thread", admission)
    assert payload == dict(
        session_data=dict(
            _document_context={"project_id": "owned-document"},
            session_id="owned-thread",
            file_ids=["file"],
            detach_files=True,
            watch_video=True,
            confirm_expensive_run=True,
            confirmed_offer_id=None,
            confirmation_decision=None,
            confirmation_cancelled=False,
            _routing_usage={"prompt": 7},
            _resolved_category="general",
        ),
        selected_model="resolved",
        route_override="general",
        input_type="text",
        web_search=False,
        deep_research=False,
        file_context="file text",
        attachments=[{"file_id": "file"}],
        memory_enabled=False,
        ldr_model="ldr",
        ldr_strategy="strategy",
        multi_intent=expected,
        planning=expected,
        persona_ids=["engineer", "2"],
    )
    assert options.route.selected_model == "manual"
    assert options.message_id == "message" and options.text == "task"
    assert "forged" not in str(payload)


@pytest.mark.parametrize("file_ids", [None, "bad-shape", {"id": "bad-shape"}])
def test_default_flags_and_malformed_file_ids_keep_existing_semantics(file_ids):
    options = parse({"file_ids": file_ids})
    assert options.file_ids is None and options.attachments is None
    assert options.memory_enabled and options.persona_ids is None
    assert options.planning is options.multi_intent is None
    assert not options.watch_video and not options.detach_files


@pytest.mark.parametrize("decision", ["accept", "decline"])
@pytest.mark.parametrize("ide", [False, True])
def test_continuation_keeps_server_content_and_ide_pin_after_admission(decision, ide):
    server = anchor()
    options = parse(
        dict(
            text="forged",
            model="forged",
            route_override="forged",
            attachments=[{"content": "forged"}],
            file_ids=["forged"],
            planning=True,
            multi_intent=False,
            persona_ids=["forged"],
            memory_enabled=True,
            file_context="forged",
            watch_video=True,
            web_search=True,
        ),
        server,
        decision,
    )
    admission = WsAdmission(options.route, None, {"repository_id": "owned-ide"} if ide else None)
    prepared = options.after_admission(admission, anchor=server, decision=decision)
    payload = prepared.worker_options(server.thread_id, admission)
    assert prepared.text == server.text
    assert payload["attachments"] == list(server.attachments)
    assert payload["session_data"]["file_ids"] == list(server.file_ids)
    assert payload["selected_model"] == "server-model"
    assert not prepared.planning and prepared.multi_intent and not prepared.memory_enabled
    assert prepared.persona_ids == ["engineer"]
    assert prepared.file_context == "PRIVATE_SERVER_CONTEXT"
    assert not prepared.watch_video
    assert prepared.route.route_override == (
        "general" if ide or decision == "decline" else "pdf_gen"
    )
    assert payload["session_data"]["confirmation_cancelled"] == (decision == "decline")
    assert payload["session_data"]["confirmation_decision"] == decision
    assert payload["session_data"]["confirmed_offer_id"] == server.offer_id
    assert "PRIVATE" not in repr(prepared)
    assert server.continuation["planning"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage", ["admission", "create", "queue_missing", "enqueue", "task_id", "accept", None]
)
async def test_offer_claim_dispatch_boundary_and_order_remain_in_handler(monkeypatch, stage):
    server = anchor()
    order = []

    def step(name):
        order.append(name)
        if stage == name:
            raise RuntimeError("synthetic failure")

    async def admit(**kwargs):
        step("admission")
        assert kwargs["user_id"] == server.user_id
        assert kwargs["text"] == server.text
        return WsAdmission(kwargs["selection"], None, None)

    async def create(**kwargs):
        step("create")
        assert str(kwargs["user_id"]) == server.user_id
        return SimpleNamespace(job_id="owned-job")

    def enqueue(**kwargs):
        step("enqueue")
        assert kwargs["user_id"] == server.user_id
        assert kwargs["job_id"] == "owned-job" and kwargs["queue"] == "agents"
        return "owned-task"

    async def task_id(*args):
        step("task_id")

    async def accept(*args, **kwargs):
        step("accept")

    release = AsyncMock()
    fallback = Mock()
    monkeypatch.setattr(
        handler, "claim_confirmation_offer", AsyncMock(return_value=(server, False))
    )
    monkeypatch.setattr(handler, "admit_ws_message", admit)
    monkeypatch.setattr(handler, "mark_confirmation_accepted", accept)
    monkeypatch.setattr(handler, "release_confirmation_claim", release)
    monkeypatch.setattr(handler, "StreamChatResponseUseCase", fallback)
    jobs = SimpleNamespace(
        create_chat_job=AsyncMock(side_effect=create),
        job_queue=None
        if stage == "queue_missing"
        else SimpleNamespace(enqueue_agent_message=enqueue),
        update_job_celery_task_id=AsyncMock(side_effect=task_id),
    )
    call = handler.HandleWsChatMessageUseCase(jobs, object()).execute(
        thread_id=server.thread_id,
        msg={"confirm_offer_id": server.offer_id, "user_id": "forged", "text": "forged"},
        session={"user_id": server.user_id},
    )
    if stage:
        with pytest.raises(RuntimeError):
            await call
        expected = ["admission", "create", "enqueue", "task_id", "accept"]
        count = 2 if stage == "queue_missing" else expected.index(stage) + 1
        assert order == expected[:count]
    else:
        result = await call
        assert result["job_id"] == "owned-job" and result["celery_task_id"] == "owned-task"
        assert order == ["admission", "create", "enqueue", "task_id", "accept"]
    if stage in {"create", "queue_missing"}:
        release.assert_awaited_once_with(None, server.offer_id)
    else:
        release.assert_not_awaited()
    fallback.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_queue_keeps_legacy_fallback_projection_and_session_identity(monkeypatch):
    user_id = str(uuid4())
    route = WsRoute("resolved", "text", "general", False, False, "general", {"prompt": 9})
    monkeypatch.setattr(
        handler, "admit_ws_message", AsyncMock(return_value=WsAdmission(route, None, None))
    )
    execute = AsyncMock(return_value={"reply": "legacy fallback"})
    monkeypatch.setattr(
        handler, "StreamChatResponseUseCase", lambda _service: SimpleNamespace(execute=execute)
    )
    jobs = SimpleNamespace(
        create_chat_job=AsyncMock(return_value=SimpleNamespace(job_id="job")), job_queue=None
    )
    result = await handler.HandleWsChatMessageUseCase(jobs, object()).execute(
        thread_id="thread",
        msg=dict(
            id="message",
            text="task",
            model="manual",
            user_id="forged-owner",
            file_context="context",
            attachments=[{"file_id": "file"}],
            file_ids=["file"],
            memory_enabled=False,
            planning=True,
            persona_ids=["engineer"],
            confirm_expensive_run=True,
        ),
        session={"user_id": user_id},
    )
    execute.assert_awaited_once_with(
        document_context=None,
        thread_id="thread",
        text="task",
        user_id=user_id,
        selected_model="resolved",
        input_type="text",
        web_search=False,
        deep_research=False,
        file_context="context",
        attachments=[{"file_id": "file"}],
        route_override="general",
        routing_metadata=None,
        confirm_expensive_run=True,
    )
    assert result["type"] == "fallback"
    assert result["message_id"] == "message" and result["selected_model"] == "resolved"
    assert result["fallback_result"] == {"reply": "legacy fallback"}


@pytest.mark.asyncio
async def test_workspace_admission_failure_prevents_job_creation_and_chat_fallback(monkeypatch):
    jobs = SimpleNamespace(create_chat_job=AsyncMock())
    monkeypatch.setattr(
        handler, "admit_ws_message", AsyncMock(side_effect=HTTPException(409, "stale"))
    )
    fallback = Mock()
    monkeypatch.setattr(handler, "StreamChatResponseUseCase", fallback)
    with pytest.raises(HTTPException):
        await handler.HandleWsChatMessageUseCase(jobs, object()).execute(
            thread_id="thread",
            msg={"ide_target_id": "stale-ticket"},
            session={"user_id": str(uuid4())},
        )
    jobs.create_chat_job.assert_not_awaited()
    fallback.assert_not_called()
