"""Неизвестная пауза/Stop не разрешает следующий inference или инструмент."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import stream_loop, workspace_control
from service.domain.runners.chat.stream_state import run_requested_tools
from service.domain.runners.harness.loop import resume_tool_round
from service.domain.tools.workspace import client
from tests.test_s25_grounding_latch import _Disclosure, _state

REFERENCE = {
    "workspace_id": "owned-workspace",
    "token": "PRIVATE_OWNER",
    "coordination_capability": "PRIVATE_COORDINATION",
}


def state_for(execution):
    return _state(execution, _Disclosure([]))


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ide_context", "document_context"])
async def test_private_boundary_is_allowed_without_exposing_mutation_authority(
    monkeypatch, surface
):
    seen = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, json, headers):
            seen.append((url, json))
            return httpx.Response(200, json={"state": "running"})

    monkeypatch.setattr(client, "_settings", lambda: ("http://workspace:8080", 30, True))
    monkeypatch.setattr(client.httpx, "AsyncClient", Client)
    ref = {**REFERENCE, surface: {"path": "documents/slides"}}
    assert await client.call(ref, "collaboration/boundary", {}) == {"state": "running"}
    assert len(seen) == 1 and seen[0][1]["coordination_capability"] == "PRIVATE_COORDINATION"
    with pytest.raises(client.WorkspaceUnavailable):
        await client.call(ref, "collaboration/boundary", {"state": "running"})
    with pytest.raises(client.WorkspaceUnavailable):
        await client.call(ref, "exec", {"command": "arbitrary"})
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response", [None, {}, {"state": "unknown"}, {"state": 1}, {"state": []}, []]
)
async def test_unknown_boundary_blocks_without_claiming_user_cancelled(monkeypatch, response):
    remote = AsyncMock(return_value=response)
    if response is None:
        remote.side_effect = client.WorkspaceUnavailable()
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        execution.harness = SimpleNamespace(failure="")
        events = [
            event
            async for event in workspace_control.workspace_safe_boundary(
                state_for(execution), agent_name="general"
            )
        ]
        assert events[-1] is True
        assert not execution.cancelled
        assert execution.harness.failure == "checkpoint_unavailable"
        assert execution.task.stop_reason == "checkpoint_unavailable"
        assert "PRIVATE" not in str(events)
    remote.assert_awaited_once_with(REFERENCE, "collaboration/boundary", {})


@pytest.mark.asyncio
async def test_stop_is_read_from_private_resources_not_prompt_context(monkeypatch):
    remote = AsyncMock(return_value={"state": "cancelled"})
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        state = state_for(execution)
        state.context = {"workspace_ref": {**REFERENCE, "coordination_capability": "WRONG"}}
        events = [
            event
            async for event in workspace_control.workspace_safe_boundary(
                state, agent_name="general"
            )
        ]
        assert events[-1] is True and execution.cancelled
    remote.assert_awaited_once_with(REFERENCE, "collaboration/boundary", {})


@pytest.mark.asyncio
async def test_unknown_boundary_never_dispatches_requested_tool(monkeypatch):
    monkeypatch.setattr(
        workspace_control, "workspace_call", AsyncMock(side_effect=client.WorkspaceUnavailable())
    )
    dispatched = []

    async def execute(*args, **kwargs):
        dispatched.append(args)
        if False:
            yield

    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        _ = [
            event
            async for event in run_requested_tools(
                state_for(execution),
                [{"name": "tool", "arguments": "{}"}],
                agent_name="general",
                execute_tool_round=execute,
            )
        ]
        assert not dispatched and execution.task.rounds == 0


@pytest.mark.asyncio
async def test_unknown_boundary_never_dispatches_first_paid_model(monkeypatch):
    monkeypatch.setattr(
        workspace_control, "workspace_call", AsyncMock(side_effect=client.WorkspaceUnavailable())
    )
    dispatched = []

    async def stream(**kwargs):
        dispatched.append(kwargs)
        if False:
            yield

    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        _ = [
            event
            async for event in stream_loop.run_streamed_tool_loop(
                state_for(execution),
                agent_name="general",
                stream=stream,
                execute_tool_round=None,
                estimate_prompt_tokens=lambda *args: 1,
            )
        ]
        assert not dispatched


@pytest.mark.asyncio
async def test_unknown_boundary_never_resumes_pending_tool(monkeypatch):
    monkeypatch.setattr(
        workspace_control, "workspace_call", AsyncMock(side_effect=client.WorkspaceUnavailable())
    )
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        execution.harness = SimpleNamespace(
            failure="",
            current=SimpleNamespace(
                continuation=SimpleNamespace(phase="tools", agent_name="general")
            ),
        )
        state = state_for(execution)
        state.convo.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "already-planned", "function": {"name": "tool", "arguments": "{}"}}
                ],
            }
        )
        _ = [event async for event in resume_tool_round(state, None)]
        assert state.finalizing and state.convo[-1]["tool_calls"][0]["id"] == "already-planned"
        assert execution.task.rounds == 0


@pytest.mark.asyncio
async def test_pause_waits_for_same_boundary_then_resumes(monkeypatch):
    remote = AsyncMock(side_effect=[{"state": "paused"}, {"state": "running"}])
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    monkeypatch.setattr(workspace_control.asyncio, "sleep", AsyncMock())
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        events = [
            event
            async for event in workspace_control.workspace_safe_boundary(
                state_for(execution), agent_name="general"
            )
        ]
        assert events[-1] is False and not execution.cancelled
        assert [event.metadata["state"] for event in events[:-1]] == ["paused", "resumed"]
        assert remote.await_count == 2


@pytest.mark.asyncio
async def test_final_answer_reserve_still_checks_stop_without_prohibiting_answer(monkeypatch):
    remote = AsyncMock(return_value={"state": "running"})
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    monkeypatch.setattr(workspace_control.deadline, "must_finalize", lambda: True)
    monkeypatch.setattr(workspace_control.deadline, "remaining", lambda: 20)
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        state = state_for(execution)
        state.finalizing = True
        events = [
            event
            async for event in workspace_control.control_gate(
                state, agent_name="general", before_model=True
            )
        ]
        assert events == [] and "workspace_control" not in state.tool_summary
    remote.assert_awaited_once()


@pytest.mark.asyncio
async def test_paused_final_answer_does_not_spend_reserve_waiting(monkeypatch):
    remote = AsyncMock(return_value={"state": "paused"})
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    monkeypatch.setattr(workspace_control.deadline, "must_finalize", lambda: True)
    monkeypatch.setattr(workspace_control.deadline, "remaining", lambda: 20)
    monkeypatch.setattr(workspace_control.asyncio, "sleep", AsyncMock())
    with use_run_execution(PrivateRunResources(workspace_ref=REFERENCE)) as execution:
        state = state_for(execution)
        _ = [
            event
            async for event in workspace_control.control_gate(
                state, agent_name="general", before_model=True
            )
        ]
        assert state.tool_summary["workspace_control"] == "blocked"
    remote.assert_awaited_once()
