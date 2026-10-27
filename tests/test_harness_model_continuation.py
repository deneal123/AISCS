"""Новый model-step после принятого ответа; repair не обнуляется при восстановлении."""

import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import stream_loop
from service.domain.runners.harness.continuation import restored_length_continuations
from service.events import AgentEvent, EventType
from service.shared.harness_protocol import Continuation, HarnessFailure
from service.shared.task_contract import TaskContract, TaskCriterion, TaskState
from tests.test_s25_grounding_latch import _configure, _Disclosure, _state, _tool


class Journal:
    def __init__(self):
        self.failure = ""
        self.current = SimpleNamespace(continuation=Continuation(call_payload_version=2))
        self.checkpoints = []
        self.slots = {}
        self.dispatches = []
        self.fail_advance = False

    async def checkpoint(self, execution, messages, *, phase, advance=False, **kwargs):
        self.checkpoints.append((advance, execution.task_state, deepcopy(messages)))
        if advance and self.fail_advance:
            raise HarnessFailure("checkpoint_unavailable")
        self.current.continuation = Continuation(
            length_continuations=kwargs.get(
                "length_continuations", self.current.continuation.length_continuations
            ),
            messages=messages,
            phase=phase,
            call_payload_version=2,
            next_step=self.current.continuation.next_step + int(advance),
        )

    def dispatch(self, messages):
        step = self.current.continuation.next_step
        digest = json.dumps(messages, sort_keys=True)
        if step in self.slots and self.slots[step] != digest:
            raise HarnessFailure("provider_state_incompatible")
        self.slots[step] = digest
        self.dispatches.append(step)


def bind(execution, *, repairs=0):
    execution.bind_task_state(
        TaskState(
            contract=TaskContract(
                task_id=str(uuid4()),
                project_id="synthetic-project",
                generation="g1",
                kind="analysis",
                goal="Прочитать a.py",
                actions=("read",),
                credit_limit=100,
                criteria=(TaskCriterion(criterion_id="source", kind="read", target="a.py"),),
            ),
            source_revision="r1",
            protocol_repairs=repairs,
        )
    )
    journal = Journal()
    execution.harness = journal
    return journal


def scripted_rounds(monkeypatch, replies):
    observed = []

    async def stream(state, round_state, **kwargs):
        state.execution.harness.dispatch(state.round_messages)
        observed.append(deepcopy(state.round_messages))
        text, reason = replies[len(observed) - 1]
        state.segment += text
        round_state.finish_reason = reason
        if not state.execution.grounding.blocks_output:
            state.collected += text
            yield AgentEvent(type=EventType.STREAM_CHUNK, agent_name="general", data=text)

    monkeypatch.setattr(stream_loop, "_stream_provider_round", stream)
    return observed


async def run(state):
    async def no_tools(*args, **kwargs):
        if False:
            yield

    return [
        event
        async for event in stream_loop.run_streamed_tool_loop(
            state,
            agent_name="general",
            execute_tool_round=no_tools,
            estimate_prompt_tokens=lambda *args: 1,
            stream=None,
        )
    ]


@pytest.mark.asyncio
async def test_grounding_repair_uses_new_slot_and_persists_protocol_budget(monkeypatch):
    scripted_rounds(monkeypatch, [("PRIVATE_REFUSAL", "stop"), ("PRIVATE_REFUSAL", "stop")])
    with use_run_execution(PrivateRunResources()) as execution:
        journal = bind(execution)
        _configure(execution)
        state = _state(execution, _Disclosure([_tool()]))
        events = await run(state)
        assert journal.dispatches == [0, 1]
        assert execution.task_state.protocol_repairs == 1
        assert execution.task_state.rounds == 0
        assert journal.current.continuation.length_continuations == 0
        advances = [item for item in journal.checkpoints if item[0]]
        assert len(advances) == 1 and advances[0][1].protocol_repairs == 1
        assert "PRIVATE_REFUSAL" not in str(events)


@pytest.mark.asyncio
async def test_restored_protocol_budget_does_not_admit_another_repair(monkeypatch):
    scripted_rounds(monkeypatch, [("PRIVATE_REFUSAL", "stop"), ("PRIVATE_REFUSAL", "stop")])
    with use_run_execution(PrivateRunResources()) as execution:
        journal = bind(execution, repairs=1)
        _configure(execution)
        state = _state(execution, _Disclosure([_tool()]))
        await run(state)
        assert journal.dispatches == [0]
        assert len(journal.checkpoints) == 1
        assert execution.task_state.protocol_repairs == 1


@pytest.mark.asyncio
async def test_length_continuation_keeps_transcript_without_reusing_paid_slot(monkeypatch):
    observed = scripted_rounds(
        monkeypatch,
        [
            ("Начало ", "length"),
            ("середина ", "length"),
            ("конец", "stop"),
        ],
    )
    with use_run_execution(PrivateRunResources()) as execution:
        journal = bind(execution)
        state = _state(execution, _Disclosure([_tool()]))
        state.max_continuations = 2
        await run(state)
        assert journal.dispatches == [0, 1, 2]
        assert journal.current.continuation.length_continuations == 2
        assert state.collected == "Начало середина конец"
        assert [item["content"] for item in observed[2] if item["role"] == "assistant"] == [
            "Начало ",
            "середина ",
        ]
        assert execution.task_state.rounds == 0


@pytest.mark.asyncio
async def test_unconfirmed_checkpoint_stops_before_another_inference(monkeypatch):
    scripted_rounds(monkeypatch, [("Начало ", "length"), ("конец", "stop")])
    with use_run_execution(PrivateRunResources()) as execution:
        journal = bind(execution)
        journal.fail_advance = True
        state = _state(execution, _Disclosure([_tool()]))
        state.max_continuations = 1
        with pytest.raises(HarnessFailure, match="checkpoint_unavailable"):
            await run(state)
        assert journal.dispatches == [0]


@pytest.mark.asyncio
async def test_restored_length_counter_does_not_admit_extra_continuation(monkeypatch):
    scripted_rounds(monkeypatch, [("Сохранённая часть ", "length")])
    with use_run_execution(PrivateRunResources()) as execution:
        journal = bind(execution)
        journal.current.continuation = Continuation(
            next_step=3,
            length_continuations=2,
            phase="model",
            call_payload_version=2,
        )
        state = _state(execution, _Disclosure([_tool()]))
        state.max_continuations = 2
        state.continuations = restored_length_continuations(execution)
        await run(state)
        assert journal.dispatches == [3]
        assert not any(advance for advance, *_ in journal.checkpoints)
