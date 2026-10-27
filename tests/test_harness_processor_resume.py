"""Frozen harness continuation bypasses fresh orchestration; no service access."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.application.harness.resume import resume_task
from service.application.processing.processor import AgentProcessor
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.events import AgentEvent, EventType
from service.shared.harness_protocol import Continuation, HarnessFailure
from tests.test_harness_reconciliation import Journal


def saved_continuation(**updates):
    return Continuation(
        **{
            "messages": [
                {"role": "system", "content": "PRIVATE_FROZEN_PROMPT"},
                {"role": "user", "content": "PRIVATE_ORIGINAL_TASK"},
            ],
            "provider": {"provider": "routerai", "model": "frozen-model"},
            "agent_name": "general",
            "phase": "model",
            **updates,
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("question_answer", [False, True])
async def test_processor_resumes_owner_without_routing_compaction_or_new_plan(question_answer):
    journal = Journal(None)
    client = journal.client()
    client.current = client.current.model_copy(
        update={
            "continuation": saved_continuation(phase="waiting_user" if question_answer else "model")
        }
    )
    processor = object.__new__(AgentProcessor)
    seen = []

    async def process(user_input, context):
        seen.append((user_input, context.thread_id))
        yield AgentEvent(type=EventType.STATUS_UPDATE, agent_name="general", data="Продолжаю")

    processor.orchestrator = SimpleNamespace(
        get_agent=Mock(return_value=SimpleNamespace(name="general", process=process))
    )
    processor._resolve_route_and_plan = AsyncMock(side_effect=AssertionError("new routing"))
    processor._build_context = AsyncMock(side_effect=AssertionError("new context"))
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        execution.bind_task_state(client.current.state)
        if question_answer:
            execution.question.resume_json = "{}"  # already admitted answer checkpoint
        events = [
            event
            async for event in processor.process_message_stream(
                "original task", "thread", execution=execution
            )
        ]
        assert execution.task.rounds == 3
        assert execution.task_state == client.current.state
        assert len(events) == 1 and events[0].data == "Продолжаю"
    assert seen == [("original task", "thread")]
    processor._resolve_route_and_plan.assert_not_awaited()
    processor._build_context.assert_not_awaited()
    processor.orchestrator.get_agent.assert_called_once_with("general")
    assert not journal.counts  # no grants, checkpoint rewrite or tool dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "fallback", "code"),
    [
        ({"agent_name": None}, False, "provider_state_incompatible"),
        ({"provider": None}, False, "provider_state_incompatible"),
        ({"phase": "final"}, False, "provider_state_incompatible"),
        ({"phase": "waiting_user"}, False, "user_decision_required"),
        ({"agent_name": "withdrawn"}, True, "provider_state_incompatible"),
    ],
)
async def test_incompatible_checkpoint_never_silently_falls_back(updates, fallback, code):
    journal = Journal(None)
    client = journal.client()
    client.current = client.current.model_copy(
        update={"continuation": saved_continuation(**updates)}
    )
    process = AsyncMock()
    processor = SimpleNamespace(
        orchestrator=SimpleNamespace(
            get_agent=Mock(return_value=SimpleNamespace(name="general", process=process))
        )
    )
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = client
        with pytest.raises(HarnessFailure, match=code):
            _ = [event async for event in resume_task(processor, "task", None, execution)]
    assert client.failure == code
    process.assert_not_called()
    assert processor.orchestrator.get_agent.call_count == int(fallback)
