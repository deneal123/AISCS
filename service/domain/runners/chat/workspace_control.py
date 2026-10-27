"""Безопасная граница между раундами: ожидание паузы и подтверждённый Stop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from service.domain.tools.workspace.client import WorkspaceUnavailable
from service.domain.tools.workspace.client import call as workspace_call
from service.events import AgentEvent, EventType
from service.shared import deadline

if TYPE_CHECKING:
    from .stream_state import ChatStreamLoopState


def _workspace_ref(context: Any | None) -> dict[str, Any] | None:
    value = (
        context.get("workspace_ref")
        if isinstance(context, dict)
        else getattr(context, "workspace_ref", None)
    )
    return value if isinstance(value, dict) and value.get("coordination_capability") else None


def _event(agent_name: str, state: str) -> AgentEvent:
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data=None,
        metadata={"kind": "workspace_collaboration", "state": state},
    )


async def workspace_safe_boundary(
    state: ChatStreamLoopState, *, agent_name: str, before_model: bool = False
) -> AsyncGenerator[AgentEvent | bool]:
    reference = _workspace_ref({"workspace_ref": state.execution.resources.workspace_ref})
    if state.execution.resources.workspace_ref is None:
        reference = _workspace_ref(state.context)
    if reference is None:
        yield False
        return
    announced_pause = False
    while True:
        remaining = deadline.remaining()
        if (remaining is not None and remaining <= 0) or (
            deadline.must_finalize() and (not before_model or announced_pause)
        ):
            yield True
            return
        try:
            response = await workspace_call(reference, "collaboration/boundary", {})
        except WorkspaceUnavailable:
            _block_unknown_control(state)
            yield _event(agent_name, "unavailable")
            yield True
            return
        boundary_state = response.get("state") if isinstance(response, dict) else None
        if not isinstance(boundary_state, str) or boundary_state not in {
            "running",
            "paused",
            "cancelled",
        }:
            _block_unknown_control(state)
            yield _event(agent_name, "unavailable")
            yield True
            return
        if boundary_state == "running":
            if announced_pause:
                yield _event(agent_name, "resumed")
            yield False
            return
        if boundary_state == "cancelled":
            state.execution.cancel()
            yield _event(agent_name, "cancelled")
            yield True
            return
        if not announced_pause:
            announced_pause = True
            yield _event(agent_name, "paused")
        await asyncio.sleep(0.5)


def _block_unknown_control(state: ChatStreamLoopState) -> None:
    state.execution.task.stop_reason = "checkpoint_unavailable"
    client = state.execution.harness
    if client is not None:
        client.failure = client.failure or "checkpoint_unavailable"


async def control_gate(
    state: ChatStreamLoopState, *, agent_name: str, before_model: bool = False
) -> AsyncGenerator[AgentEvent]:
    async with aclosing(
        workspace_safe_boundary(state, agent_name=agent_name, before_model=before_model)
    ) as boundary:
        async for event in boundary:
            if isinstance(event, bool):
                if event:
                    state.finalizing = True
                    state.tool_summary["workspace_control"] = (
                        "cancelled" if state.execution.cancelled else "blocked"
                    )
            else:
                yield event
