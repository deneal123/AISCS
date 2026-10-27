"""Preparation keeps transcript, policy and event/activation ownership distinct."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.domain.capabilities.tools.spec import ToolSet
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import preparation, run
from service.domain.runners.chat.disclosure import DisclosureUpdate
from service.domain.runners.tool_runtime import ToolCallCache
from service.domain.usage.ledger import UsageKind, UsageLedger
from service.events import AgentEvent, EventType


def tool(name):
    return {"type": "function", "function": {"name": name}}


@pytest.fixture
def setup(monkeypatch):
    order = []
    messages = [{"role": "system", "content": "original"}, {"role": "user", "content": "task"}]
    eligible = ToolSet(tools=[tool("ws_read"), tool("fetch_url")])
    selected = ToolSet(tools=[tool("ws_read")])
    event = AgentEvent(type=EventType.STATUS_UPDATE, metadata={"kind": "synthetic_selection"})
    disclosure = DisclosureUpdate(selected, [event], 37, preferred_tool="ws_read")

    async def resolve(*args):
        order.append("policy")
        return eligible

    async def select(controller, **kwargs):
        order.append("selection")
        assert controller.eligible_toolset is eligible
        assert kwargs == {"stage": 1, "remaining_prompt_tokens": 1200}
        return disclosure

    def context(*args):
        order.append("tool_context")
        return "private-tool-context"

    owner = SimpleNamespace(
        name="synthetic",
        max_turns=4,
        _resolve_chat_model=AsyncMock(return_value="synthetic-model"),
        _build_messages=Mock(return_value=messages),
        _resolve_toolset=AsyncMock(side_effect=resolve),
        _build_tool_context=Mock(side_effect=context),
        _execute_tool_round=AsyncMock(),
    )
    monkeypatch.setattr(preparation, "_round_limits", lambda: (900, 2))
    monkeypatch.setattr(preparation, "prompt_budget_per_run", lambda: 1200)
    monkeypatch.setattr(preparation, "_tool_dedup_mode", lambda: "enforce")
    monkeypatch.setattr(preparation.ToolSelectionController, "select", select)
    return SimpleNamespace(
        owner=owner, order=order, messages=messages, eligible=eligible, disclosure=disclosure
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["fresh", "harness", "human", "both"])
async def test_transcript_precedence_preserves_checkpoint_and_caller_messages(setup, source):
    harness_messages = [{"role": "system", "content": "frozen-harness"}]
    human_messages = [{"role": "system", "content": "frozen-human"}]
    with use_run_execution(PrivateRunResources()) as execution:
        if source in {"harness", "both"}:
            execution.harness = SimpleNamespace(
                current=SimpleNamespace(
                    state=None,
                    continuation=SimpleNamespace(
                        messages=harness_messages, conversation=lambda: list(harness_messages)
                    ),
                )
            )
        if source in {"human", "both"}:
            execution.question.resume_json = json.dumps(
                {"model": "synthetic-model", "messages": human_messages}
            )
        prepared = await preparation.prepare_chat_run(
            setup.owner, question="task", context=None, model="synthetic-model", execution=execution
        )
    expected = (
        "frozen-human"
        if source in {"human", "both"}
        else "frozen-harness"
        if source == "harness"
        else "original"
    )
    assert prepared.messages[0]["content"].startswith(expected)
    if source != "fresh":
        assert "original" not in str(prepared.messages)
    if source != "fresh":
        setup.owner._build_messages.assert_not_called()
    if source in {"human", "both"}:
        assert json.loads(execution.question.resume_json)["messages"] == human_messages
    if source == "fresh":
        setup.owner._build_messages.assert_called_once_with("task", None)
    assert setup.messages[0]["content"] == "original"
    assert harness_messages == [{"role": "system", "content": "frozen-harness"}]
    assert setup.order == ["policy", "selection"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,active", [(None, False), ("ide_context", True), ("document_context", True)]
)
async def test_activation_retains_task_rounds_authorized_index_and_run_cache(setup, kind, active):
    reference = {kind: {}} if kind else {}
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        execution.task.rounds = 7
        cache = execution.tool_cache = ToolCallCache()
        prepared = await preparation.prepare_chat_run(
            setup.owner, question="task", context=None, model="synthetic-model", execution=execution
        )
        assert execution.task.active is active
        assert execution.tool_cache is cache
        assert execution.usage.cursor() == 0
        events = list(prepared.events())
        assert [event.metadata["kind"] for event in events] == [
            "synthetic_selection",
            "tool_availability",
        ]
        assert setup.order == ["policy", "selection"]
        state = prepared.start_loop(setup.owner)
        assert execution.task.rounds == 7
    assert state.execution is execution
    assert state.tool_cache is cache
    assert state.max_tool_rounds == (9 if kind == "ide_context" else 8)
    assert state.openai_tools is setup.disclosure.toolset.tools
    assert set(state.tool_index) == {"ws_read", "fetch_url"}
    assert state.max_tokens == 900 and state.max_continuations == 2
    assert state.prompt_budget == 1200 and state.estimated_prompt_spent == 37
    assert state.tool_choice == {"type": "function", "function": {"name": "ws_read"}}
    assert state.tool_dedup_mode == "enforce"
    assert state.tool_ctx == "private-tool-context"
    assert state.usage_scope.kind == UsageKind.CHAT
    assert state.convo == state.messages == state.round_messages
    assert state.convo is not state.messages and state.round_messages is not state.messages


@pytest.mark.asyncio
async def test_activation_uses_its_explicit_owner_not_an_ambient_chat_run(setup):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        execution.task.rounds = 15
        prepared = await preparation.prepare_chat_run(
            setup.owner, question="task", context=None, model="synthetic-model", execution=execution
        )
    state = prepared.start_loop(setup.owner)
    assert state.max_tool_rounds == 1
    assert state.execution is execution
    assert execution.task.rounds == 15


@pytest.mark.asyncio
@pytest.mark.parametrize("close_after_preparation", [False, True])
async def test_real_runner_yields_availability_before_usage_scope_and_primary_model(
    monkeypatch, setup, close_after_preparation
):
    original_scope = UsageLedger.open_scope

    def scope(ledger, **kwargs):
        setup.order.append("scope")
        return original_scope(ledger, **kwargs)

    async def loop(state, **kwargs):
        setup.order.append("primary_model")
        state.collected = "answer"
        yield AgentEvent(type=EventType.STREAM_CHUNK, data="answer")

    monkeypatch.setattr(UsageLedger, "open_scope", scope)
    monkeypatch.setattr(run, "run_streamed_tool_loop", loop)
    stream = run.ChatRunMixin._run_chat_streamed(setup.owner, "task", None)
    assert (await anext(stream)).metadata["kind"] == "synthetic_selection"
    assert (await anext(stream)).metadata["kind"] == "tool_availability"
    assert setup.order == ["policy", "selection"]
    if close_after_preparation:
        await stream.aclose()
        setup.owner._build_tool_context.assert_not_called()
    else:
        events = [event async for event in stream]
        assert setup.order == ["policy", "selection", "tool_context", "scope", "primary_model"]
        assert events[-1].type == EventType.AGENT_COMPLETE
    setup.owner._execute_tool_round.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["policy", "selection"])
async def test_preparation_failure_never_activates_model_or_tool_context(monkeypatch, setup, fault):
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic preparation failure")

    if fault == "policy":
        setup.owner._resolve_toolset.side_effect = fail
    else:
        monkeypatch.setattr(preparation.ToolSelectionController, "select", fail)
    dispatch = Mock()
    monkeypatch.setattr(run, "run_streamed_tool_loop", dispatch)
    stream = run.ChatRunMixin._run_chat_streamed(setup.owner, "task", None)
    with pytest.raises(RuntimeError, match="synthetic preparation failure"):
        await anext(stream)
    setup.owner._build_tool_context.assert_not_called()
    dispatch.assert_not_called()
    setup.owner._execute_tool_round.assert_not_awaited()
