import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from service.services.chat.application.ide.run_ticket import issue_ticket, read_ticket
from service.services.chat.application.use_cases.ws_message.handler import (
    HandleWsChatMessageUseCase,
)


@pytest.mark.asyncio
async def test_ticket_is_owner_thread_scoped_and_expires_without_private_binding():
    redis = SimpleNamespace(set=AsyncMock(), get=AsyncMock())
    thread, user, repo = (str(uuid4()) for _ in range(3))
    target = dict(repository_id=repo, generation="a" * 64)
    ticket = await issue_ticket(redis, thread_id=thread, user_id=user, target=target)
    args, kwargs = redis.set.call_args
    assert kwargs["ex"] == 120
    redis.get.return_value = args[1]
    resolved = await read_ticket(redis, thread_id=thread, user_id=user, ticket=ticket["target_id"])
    assert resolved["repository_id"] == repo and "token" not in resolved
    for other_thread, other_user in [(str(uuid4()), user), (thread, str(uuid4()))]:
        with pytest.raises(HTTPException):
            await read_ticket(
                redis, thread_id=other_thread, user_id=other_user, ticket=ticket["target_id"]
            )
    redis.get.return_value = None
    with pytest.raises(HTTPException):
        await read_ticket(redis, thread_id=thread, user_id=user, ticket=ticket["target_id"])


@pytest.mark.asyncio
async def test_ide_socket_routes_without_llm_router_and_never_falls_back_on_unknown_enqueue():
    thread, user, repo, ticket = (str(uuid4()) for _ in range(4))
    target = dict(repository_id=repo, generation="a" * 64)
    redis = SimpleNamespace(
        get=AsyncMock(return_value=json.dumps(dict(thread_id=thread, user_id=user, target=target)))
    )
    queue = SimpleNamespace(enqueue_agent_message=Mock(return_value="task"))
    jobs = SimpleNamespace(
        create_chat_job=AsyncMock(return_value=SimpleNamespace(job_id=uuid4())),
        job_queue=queue,
        update_job_celery_task_id=AsyncMock(),
    )
    chat = SimpleNamespace(
        routing_service=SimpleNamespace(resolve_route=AsyncMock()), post_message=AsyncMock()
    )
    use_case = HandleWsChatMessageUseCase(jobs, chat, redis)
    msg = dict(text="Edit", ide_target_id=ticket, route_override="pdf_gen")
    assert (await use_case.execute(thread_id=thread, msg=msg, session=dict(user_id=user)))[
        "type"
    ] == "job_created"
    queued = queue.enqueue_agent_message.call_args.kwargs
    assert queued["session_data"]["_ide_context"]["repository_id"] == repo
    assert queued["route_override"] == "general"
    chat.routing_service.resolve_route.assert_not_awaited()
    queue.enqueue_agent_message.side_effect = RuntimeError("uncertain enqueue")
    with pytest.raises(RuntimeError):
        await use_case.execute(thread_id=thread, msg=msg, session=dict(user_id=user))
    chat.post_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_ide_confirmation_cannot_fall_back_to_ordinary_rest_chat(monkeypatch):
    from service.services.chat.application.chat_application_service import ChatApplicationService
    from service.services.chat.domain.confirmation import offer as confirmation_offer

    chat = SimpleNamespace(
        persistence_service=SimpleNamespace(get_thread_owner=AsyncMock(return_value="owner")),
        post_message=AsyncMock(),
    )
    service = ChatApplicationService(chat, None)
    monkeypatch.setattr(
        confirmation_offer,
        "read_confirmation_offer",
        AsyncMock(
            return_value=SimpleNamespace(
                continuation={"ide_context": {"repository_id": str(uuid4())}}
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        await service.post_message("thread", SimpleNamespace(confirm_offer_id="offer"), "owner")
    assert error.value.status_code == 503
    chat.post_message.assert_not_awaited()
