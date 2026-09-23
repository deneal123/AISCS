"""Catalog selection before the normal decomposition fallback.

This is intentionally separate from ``processor_steps``: catalog retrieval has its
own failure model and must not obscure the ordinary route/decomposition state machine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from service.domain.capabilities import get_workflow
from service.domain.capabilities.agent_spec import COST_CHEAP
from service.domain.pipeline.decomposition import decomposition_allowed
from service.domain.run_context import RunExecutionContext
from service.domain.workflows import catalog
from service.events import AgentEvent


@dataclass(frozen=True, slots=True)
class CatalogSelection:
    subtasks: list | None
    candidate: Any | None
    events: list[AgentEvent]
    route_override: str | None
    resolved_category: str | None
    blocked_for_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class WorkflowRoute:
    """Resolved chain before the normal single-agent route is selected."""

    subtasks: list | None
    candidate: Any | None
    events: list[AgentEvent]
    route_override: str | None
    resolved_category: str | None


async def select_catalog_workflow(
    *, user_input: str, route_override: str | None, resolved_category: str | None
) -> CatalogSelection:
    """Select a current safe candidate, or return the untouched regular route state.

    An opaque confirmation identifier is accepted only when the same workflow version is
    among the current top-five retrieval candidates.  A failed read is therefore exactly
    the normal fallback, never an implicit authorization for an old or forged chain.
    """
    requested = catalog.requested_route(route_override)
    allowed = requested is not None or (
        not route_override and resolved_category in {None, "general"}
    )
    if not allowed:
        return CatalogSelection(None, None, [], route_override, resolved_category)
    candidates = await catalog.retrieve(user_input)
    candidate = (
        catalog.confirmed_candidate(candidates, route_override)
        if requested is not None
        else (candidates[0] if candidates else None)
    )
    spec = catalog.to_workflow_spec(candidate) if candidate is not None else None
    if spec is not None and candidate is not None:
        # The catalog class is only an index hint; gates and trace use current specs.
        candidate = replace(candidate, cost_class=spec.cost_class)
    if (
        spec is not None
        and candidate is not None
        and (spec.cost_class == COST_CHEAP or requested is not None)
    ):
        return CatalogSelection(
            spec.instantiate(user_input), candidate, [], route_override, resolved_category
        )
    if spec is not None and candidate is not None and not route_override:
        return CatalogSelection(
            None,
            None,
            [catalog.confirmation_offer(candidate, user_input)],
            route_override,
            resolved_category,
            blocked_for_confirmation=True,
        )
    if requested is not None:
        # A stale or forged confirmation token goes to the old safe fallback.
        return CatalogSelection(None, None, [], None, None)
    return CatalogSelection(None, None, [], route_override, resolved_category)


async def resolve_workflow_route(
    *,
    user_input: str,
    route_override: str | None,
    resolved_category: str | None,
    multi_intent: bool | None,
    web_search: bool,
    deep_research: bool,
    input_type: str | None,
    force_decompose: bool,
    max_subtasks: int,
    model: str,
    execution: RunExecutionContext | None,
    decompose: Callable[..., Awaitable[list]],
) -> WorkflowRoute:
    """Prefer declared/catalog chains, then preserve ordinary decomposition fallback."""
    if workflow := get_workflow(resolved_category or ""):
        return WorkflowRoute(
            workflow.instantiate(user_input), None, [], route_override, resolved_category
        )
    allowed = decomposition_allowed(
        multi_intent=multi_intent,
        route_override=route_override,
        web_search=web_search,
        deep_research=deep_research,
        input_type=input_type,
    )
    if not (allowed or route_override):
        return WorkflowRoute(None, None, [], route_override, resolved_category)
    selection = await select_catalog_workflow(
        user_input=user_input,
        route_override=route_override,
        resolved_category=resolved_category,
    )
    allowed_after_selection = decomposition_allowed(
        multi_intent=multi_intent,
        route_override=selection.route_override,
        web_search=web_search,
        deep_research=deep_research,
        input_type=input_type,
    )
    subtasks = selection.subtasks
    if not selection.blocked_for_confirmation and subtasks is None and allowed_after_selection:
        subtasks = await decompose(
            user_input,
            force=force_decompose,
            max_subtasks=max_subtasks,
            model=model,
            execution=execution,
        )
    return WorkflowRoute(
        subtasks,
        selection.candidate,
        selection.events,
        selection.route_override,
        selection.resolved_category,
    )
