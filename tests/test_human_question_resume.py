"""Resume the next model round, not the original request or completed tools."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from service.application.human_questions.admission import apply_human_question_context
from service.application.human_questions.resume import RESUME_KEY, admit_question_resume
from service.application.processing.processor import AgentProcessor
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import run as chat_run
from service.events import EventType
from service.shared.human_question import (
    HumanQuestionError,
    QuestionPrompt,
    parse_resumed_question_continuation,
    resume_question_continuation,
)


def checkpoint():
    prompt = QuestionPrompt.parse({"prompt": "Какие папки добавить?", "choices": []})
    pending = {
        "model": "test-model",
        "tool_call_id": "question",
        "messages": [
            {"role": "system", "content": "ORIGINAL-PROCEDURE"},
            {"role": "user", "content": "Добавь README и уточни структуру"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "old-write",
                        "type": "function",
                        "function": {
                            "name": "ide_write_file",
                            "arguments": '{"content":"PRIVATE-OLD-SOURCE"}',
                        },
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "old-write", "content": '{"written":true}'},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "question",
                        "type": "function",
                        "function": {
                            "name": "ask_user_question",
                            "arguments": json.dumps(prompt.payload()),
                        },
                    },
                ],
            },
            {"role": "tool", "tool_call_id": "question", "content": '{"awaiting_user":true}'},
        ],
    }
    return resume_question_continuation(pending, prompt, {"choice_id": None, "text": "src и tests"})


def resources(raw=None):
    return PrivateRunResources(
        workspace_ref={
            "token": "PRIVATE-CAPABILITY",
            "human_questions_enabled": True,
            "document_context": {"project_id": str(uuid4())},
            RESUME_KEY: checkpoint() if raw is None else raw,
        }
    )


def provider(execution):
    execution.provider_admission = SimpleNamespace(
        snapshot=SimpleNamespace(
            active_provider="routerai", release=lambda: None, owner_for=lambda model: "routerai"
        )
    )
    assert apply_human_question_context(execution)


@pytest.mark.parametrize("fault", ["field", "tool", "unbalanced", "answer", "oversize", "pending"])
def test_answered_checkpoint_is_closed_complete_and_bounded(fault):
    raw = checkpoint()
    if fault == "field":
        raw["capability"] = "SECRET"
    if fault == "tool":
        raw["messages"][-2]["tool_calls"][0]["function"]["name"] = "ws_run"
    if fault == "unbalanced":
        raw["messages"].pop(3)
    if fault == "answer":
        raw["messages"][-1]["content"] = '{"answer":{"choice_id":"foreign","text":null}}'
    if fault == "oversize":
        raw["messages"][0]["content"] = "x" * (1024 * 1024)
    if fault == "pending":
        raw["messages"][-1]["content"] = '{"awaiting_user":true}'
    with pytest.raises(HumanQuestionError):
        parse_resumed_question_continuation(raw)


def test_resume_requires_current_server_capability_and_same_model_and_is_private():
    with use_run_execution(resources()) as execution:
        with pytest.raises(HumanQuestionError):
            admit_question_resume(execution, "test-model")
        provider(execution)
        with pytest.raises(HumanQuestionError):
            admit_question_resume(execution, "other-model")
        assert admit_question_resume(execution, "test-model")
        before = checkpoint()
        messages = execution.question.resumed_messages("test-model")
        messages[0]["content"] = "MUTATED"
        assert execution.question.resumed_messages("test-model") == before["messages"]
        assert "PRIVATE" not in repr(execution.question)
        assert "src и tests" not in repr(execution.question)
        with pytest.raises(HumanQuestionError):
            execution.question.resumed_messages("other-model")


@pytest.mark.asyncio
async def test_resume_skips_routing_rebuild_and_completed_tool_invocation(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("completed tool or route replayed")

    monkeypatch.setattr("service.domain.tools.ide.tools.call", forbidden)
    monkeypatch.setattr("service.domain.tools.workspace.client.call", forbidden)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_supports_tools", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "service.domain.client.registry.qualify_model",
        AsyncMock(return_value=SimpleNamespace(model="test-model")),
    )
    monkeypatch.setattr(
        "service.domain.subagents.general.GeneralAgent._input_guardrail_block",
        AsyncMock(return_value=None),
    )
    seen = []

    async def stream(*, messages, model, round_state, **kwargs):
        seen.append(copy.deepcopy(messages))
        assert messages == checkpoint()["messages"]
        assert json.loads(messages[-1]["content"])["answer"]["text"] == "src и tests"
        assert "PRIVATE-CAPABILITY" not in json.dumps(messages)
        round_state.update(
            {"model": model, "prompt": 7, "completion": 3, "total": 10, "finish_reason": "stop"}
        )
        yield "Ответ принят, можно продолжать."

    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    processor = AgentProcessor({"model": "test-model"})
    monkeypatch.setattr(processor, "_resolve_route_and_plan", forbidden)
    monkeypatch.setattr(processor, "_build_context", forbidden)
    with use_run_execution(resources()) as execution:
        provider(execution)
        assert admit_question_resume(execution, "test-model")
        events = [
            event
            async for event in processor.process_message_stream(
                "Добавь README и уточни структуру",
                "thread",
                execution=execution,
            )
        ]
        assert execution.workspace.ide_reads == {} and execution.workspace.ide_writes == {}
        complete = next(event for event in events if event.type == EventType.AGENT_COMPLETE)
        assert complete.metadata["token_usage"]["total"] == 10
    assert len(seen) == 1
    assert not any(event.type == EventType.TOOL_CALL_START for event in events)
    assert any(event.type == EventType.AGENT_COMPLETE for event in events)
    public = json.dumps([event.model_dump() for event in events], default=str)
    assert "PRIVATE" not in public and "src и tests" not in public
