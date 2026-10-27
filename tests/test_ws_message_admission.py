"""Workspace validation is fail-closed; only ordinary routing may be fail-open."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from service.services.chat.application.documents import context as document_context_service
from service.services.chat.application.ide import run_ticket as ide_run_ticket
from service.services.chat.application.use_cases.ws_message.admission import (
    WsRoute,
    admit_ws_message,
)


@pytest.fixture
def prepare(monkeypatch):
    document = AsyncMock(return_value=None)
    ticket = AsyncMock(return_value=None)
    route = AsyncMock(return_value=None)
    monkeypatch.setattr(document_context_service, "validate_document_context", document)
    monkeypatch.setattr(ide_run_ticket, "read_ticket", ticket)

    async def run(msg=None, anchor=None):
        return await admit_ws_message(
            redis_client=None,
            routing_service=SimpleNamespace(resolve_route=route),
            thread_id="thread",
            user_id="authenticated",
            text="task",
            msg=msg or {},
            confirmation_anchor=anchor,
            selection=WsRoute("manual", "text", "pdf_gen", True, True),
        )

    return run, document, ticket, route


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["document", "ticket"])
async def test_invalid_workspace_scope_never_reaches_router(prepare, which):
    run, document, ticket, route = prepare
    (document if which == "document" else ticket).side_effect = HTTPException(409, "stale")
    with pytest.raises(HTTPException) as error:
        await run({"ide_target_id": "ticket"})
    assert error.value.status_code == 409
    route.assert_not_awaited()


@pytest.mark.asyncio
async def test_ide_and_document_cannot_be_combined(prepare):
    run, document, ticket, route = prepare
    document.return_value = {"project_id": "owned-document"}
    ticket.return_value = {"repository_id": "owned-repository"}
    with pytest.raises(HTTPException) as error:
        await run({"ide_target_id": "ticket"})
    assert error.value.status_code == 422
    route.assert_not_awaited()


@pytest.mark.asyncio
async def test_ide_pins_general_and_suppresses_search_without_leaking_context(prepare):
    run, _, ticket, route = prepare
    ticket.return_value = {"repository_id": "owned", "private": "PRIVATE_BINDING"}
    result = await run({"ide_target_id": "ticket", "user_id": "forged"})
    ticket.assert_awaited_once_with(
        None, thread_id="thread", user_id="authenticated", ticket="ticket"
    )
    assert result.route.route_override == result.route.resolved_category == "general"
    assert not result.route.web_search and not result.route.deep_research
    assert "PRIVATE_BINDING" not in repr(result)
    route.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmation_uses_server_context_without_reinterpreting_browser_ticket(prepare):
    run, document, ticket, route = prepare
    target = {"repository_id": "owned"}
    anchor = SimpleNamespace(continuation={"ide_context": target})
    result = await run({"ide_target_id": "forged"}, anchor)
    assert result.ide_context is target
    document.assert_awaited_once_with(None, "thread", "authenticated", None)
    ticket.assert_not_awaited()
    route.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_router_failure_preserves_explicit_selection(prepare):
    run, _, _, route = prepare
    route.side_effect = TimeoutError()
    result = await run()
    assert result.route.selected_model == "manual"
    assert result.route.route_override == "pdf_gen"
    assert result.route.web_search and result.route.deep_research
    route.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_uses_shared_routing_decision_and_usage(prepare):
    run, _, _, route = prepare
    route.return_value = SimpleNamespace(
        selected_model="resolved",
        route_override="general",
        web_search=False,
        deep_research=False,
        routing_usage={"prompt": 10},
        resolved_category="general",
    )
    result = await run()
    assert result.route.selected_model == "resolved"
    assert result.route.routing_usage == {"prompt": 10}
    assert not result.route.web_search
