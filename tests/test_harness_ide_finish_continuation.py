"""Восстановление пропущенного отчёта — новый slot с общими лимитами, не второй цикл."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.client.protocol import ProviderStreamEventKind
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import workspace_control
from service.domain.runners.ide import completion
from service.shared.harness_protocol import HarnessFailure
from tests.test_harness_model_continuation import bind
from tests.test_s25_grounding_latch import _Disclosure, _state


def state_for(execution):
    state = _state(execution, _Disclosure([{"function": {"name": "ide_finish_task"}}]))
    state.tool_index = {"ide_finish_task": object()}
    state.segment = "Файл изменён; проверка недоступна."
    state.collected = state.segment
    return state


def model(monkeypatch, journal, calls):
    async def events(stream, **kwargs):
        journal.dispatch(kwargs["messages"])
        calls.append(kwargs)
        yield SimpleNamespace(
            kind=ProviderStreamEventKind.TOOL_CALLS,
            tool_calls=[{"id": "finish-1", "name": "ide_finish_task", "arguments": "{}"}],
        )

    monkeypatch.setattr(completion, "provider_events", events)


async def run(state, executed):
    async def execute(messages, calls, *args, **kwargs):
        executed.extend(calls)
        if False:
            yield

    return [
        event
        async for event in completion.finish_ide_response(
            state,
            agent_name="general",
            stream=None,
            execute_tool_round=execute,
            estimate_prompt_tokens=lambda *args: 1,
        )
    ]


@pytest.mark.asyncio
async def test_report_repair_advances_paid_slot_before_dispatch(monkeypatch):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        journal = bind(execution)
        state = state_for(execution)
        journal.dispatch(state.round_messages)
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        await run(state, executed)
        assert journal.dispatches == [0, 1]
        assert len(calls) == len(executed) == 1
        assert execution.task_state.protocol_repairs == 1
        assert execution.task_state.rounds == state.tool_rounds == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_timeout", [120.0, 240.0])
async def test_report_timeout_follows_transport_within_task_deadline(monkeypatch, provider_timeout):
    observed = []
    monkeypatch.setattr(completion, "max_provider_timeout_sec", lambda: provider_timeout)
    monkeypatch.setattr(completion.deadline, "clamp", lambda value: observed.append(value) or 2.0)
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        journal = bind(execution)
        state = state_for(execution)
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        await run(state, executed)
        assert provider_timeout + 5.0 in observed
        assert len(calls) == len(executed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exhausted", ["protocol", "rounds"])
async def test_report_repair_cannot_reset_job_limits(monkeypatch, exhausted):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        journal = bind(execution, repairs=1 if exhausted == "protocol" else 0)
        state = state_for(execution)
        if exhausted == "rounds":
            execution.task_state = execution.task_state.advance(rounds=16)
            execution.task.rounds = state.tool_rounds = 16
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        await run(state, executed)
        assert not calls and not executed and not journal.dispatches


@pytest.mark.asyncio
async def test_unknown_checkpoint_ack_does_not_dispatch_report_repair(monkeypatch):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        journal = bind(execution)
        journal.fail_advance = True
        state = state_for(execution)
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await run(state, executed)
        assert not calls and not executed and not journal.dispatches


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["verification_unavailable", "usage_limit_exceeded"])
async def test_blocked_verification_cannot_consume_report_repair_or_another_paid_slot(
    monkeypatch, code
):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        journal = bind(execution)
        execution.harness.failure = code
        state = state_for(execution)
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        await run(state, executed)
        assert not calls and not executed and not journal.dispatches
        assert execution.task_state.protocol_repairs == 0


@pytest.mark.asyncio
async def test_stop_after_report_model_result_prevents_terminal_tool(monkeypatch):
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        bind(execution)
        state = state_for(execution)
        executed = []

        async def events(stream, **kwargs):
            execution.cancel()
            yield SimpleNamespace(
                kind=ProviderStreamEventKind.TOOL_CALLS,
                tool_calls=[{"id": "finish-1", "name": "ide_finish_task", "arguments": "{}"}],
            )

        monkeypatch.setattr(completion, "provider_events", events)
        await run(state, executed)
        assert not executed and execution.task_state.rounds == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_before_model", [False, True])
async def test_report_repair_observes_private_workspace_stop_at_both_boundaries(
    monkeypatch, stop_before_model
):
    states = ["cancelled"] if stop_before_model else ["running", "cancelled"]
    remote = AsyncMock(side_effect=[{"state": state} for state in states])
    monkeypatch.setattr(workspace_control, "workspace_call", remote)
    reference = {"ide_context": {}, "coordination_capability": "PRIVATE_COORDINATION"}
    with use_run_execution(PrivateRunResources(workspace_ref=reference)) as execution:
        journal = bind(execution)
        state = state_for(execution)
        calls, executed = [], []
        model(monkeypatch, journal, calls)
        await run(state, executed)
        assert execution.cancelled and not executed
        assert len(calls) == (0 if stop_before_model else 1)
        assert execution.task.rounds == 0
        assert execution.task_state.protocol_repairs == (0 if stop_before_model else 1)
