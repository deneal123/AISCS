"""Early routing boundary: modality, source consent and the auto-orchestrator.

No fan-out, decomposition, agent selection or planning starts until this stage
returns a non-parked result. Model calls retain the caller's execution/ledger;
preparation cannot create an independent budget, provider or usage owner.
"""

from __future__ import annotations

from service.application.processing import settings
from service.application.processing.context import attachment_text_reaches_prompt
from service.application.processing.routing.contracts import (
    RouteDecision,
    RouteInputs,
    RoutePreparation,
)
from service.application.repo_map import is_repo_map
from service.domain.execution.context import RunExecutionContext
from service.domain.pipeline.auto_mode import apply_plan, resolve_auto_plan
from service.domain.pipeline.multimodal import normalize_attachments, should_fan_out
from service.events import AgentEvent


def _park_confirmation(
    execution: RunExecutionContext, events: list[AgentEvent], file_context: str | None
) -> RoutePreparation:
    from service.domain.pipeline.confirmation import waiting_event

    execution.policy.set_flag("confirmation_pending", True)
    return RoutePreparation(
        parked=RouteDecision("general", None, None, file_context or "", False),
        events=[*events, waiting_event()],
    )


async def prepare_route(
    request: RouteInputs, *, execution: RunExecutionContext, model: str | None
) -> RoutePreparation:
    """Normalize inputs and enforce confirmation before any downstream stage."""
    from service.domain.pipeline.video_offer import explicit_video_offer

    attachments = normalize_attachments(request.attachments)
    multimodal = should_fan_out(attachments, route_override=request.route_override)
    offer = explicit_video_offer(
        request.user_input,
        request.context,
        execution,
        route_override=request.route_override,
        resolved_category=request.resolved_category,
    )
    if offer is not None:
        return _park_confirmation(execution, [offer], request.file_context)

    auto = await resolve_auto_plan(
        user_input=request.user_input,
        context=request.context,
        history_messages=request.history_messages,
        compact_summary=request.compact_summary,
        route_override=request.route_override,
        input_type=request.input_type,
        web_search=request.web_search,
        deep_research=request.deep_research,
        multimodal=multimodal,
        resolved_category=request.resolved_category,
        attachments=attachments,
        multi_intent=request.multi_intent,
        planning=request.planning,
        model=model,
        execution=execution,
        # A repository map is not file content: preserve the real prompt projection.
        attachment_text_in_prompt=attachment_text_reaches_prompt(
            request.context, request.file_context
        ),
        attachment_text_in_prompt_is_a_map=is_repo_map(request.file_context),
        **settings._orchestrator_flags(),
    )
    if auto.offered_mode or auto.offered_tool:
        return _park_confirmation(execution, auto.events, request.file_context)
    multi_intent, planning, resolved_category = apply_plan(
        auto,
        context=request.context,
        multi_intent=request.multi_intent,
        planning=request.planning,
        resolved_category=request.resolved_category,
        execution=execution,
    )
    return RoutePreparation(
        attachments=attachments,
        multimodal=multimodal,
        multi_intent=multi_intent,
        planning=planning,
        resolved_category=resolved_category,
        force_decompose=auto.force_decompose,
        events=list(auto.events),
    )
