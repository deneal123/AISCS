"""Validate WS workspace authority before resolving the shared chat route.

Workspace tickets and document scope are authoritative; a routing outage may
preserve a chat selection, but must never turn a workspace request into chat.
"""

from dataclasses import dataclass, field, replace
from typing import Any

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class WsRoute:
    selected_model: str | None
    input_type: Any
    route_override: str | None
    web_search: bool
    deep_research: bool
    resolved_category: str | None = None
    routing_usage: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WsAdmission:
    route: WsRoute
    document_context: dict[str, Any] | None = field(repr=False)
    ide_context: dict[str, Any] | None = field(repr=False)


async def admit_ws_message(
    *,
    redis_client: Any,
    routing_service: Any,
    thread_id: str,
    user_id: str,
    text: str | None,
    msg: dict[str, Any],
    confirmation_anchor: Any,
    selection: WsRoute,
) -> WsAdmission:
    from service.services.chat.application.documents.context import validate_document_context
    from service.services.chat.application.ide.run_ticket import read_ticket

    raw_document = (
        confirmation_anchor.continuation.get("document_context")
        if confirmation_anchor
        else msg.get("document_context")
    )
    document_context = await validate_document_context(
        redis_client, thread_id, user_id, raw_document
    )
    ide_context = (
        confirmation_anchor.continuation.get("ide_context") if confirmation_anchor else None
    )
    if confirmation_anchor is None and msg.get("ide_target_id") is not None:
        ide_context = await read_ticket(
            redis_client, thread_id=thread_id, user_id=user_id, ticket=msg["ide_target_id"]
        )
    if ide_context:
        if document_context:
            raise HTTPException(422, "ide_agent_context_invalid")
        selection = replace(
            selection,
            route_override="general",
            resolved_category="general",
            web_search=False,
            deep_research=False,
        )
    elif document_context:
        selection = replace(selection, resolved_category=selection.route_override or "general")
    if (
        confirmation_anchor is None
        and routing_service is not None
        and not (document_context or ide_context)
    ):
        # Same resolver as REST. Only ordinary chat routing is fail-open;
        # workspace validation above is intentionally outside this handler.
        try:
            decision = await routing_service.resolve_route(
                text=str(text or ""),
                selected_model=selection.selected_model,
                input_type=selection.input_type,
                web_search=selection.web_search,
                deep_research=selection.deep_research,
                route_override=selection.route_override,
            )
        except Exception:
            decision = None
        if decision is not None:
            selection = replace(
                selection,
                selected_model=decision.selected_model,
                route_override=decision.route_override,
                web_search=bool(decision.web_search),
                deep_research=bool(decision.deep_research),
                routing_usage=dict(decision.routing_usage or {}) or None,
                resolved_category=decision.resolved_category,
            )
    return WsAdmission(selection, document_context, ide_context)
