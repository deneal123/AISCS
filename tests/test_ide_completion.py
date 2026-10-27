import json

import pytest

from service.domain.capabilities.tools.spec import ToolSet
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import run as chat_run
from service.domain.subagents.general import GeneralAgent
from service.domain.tools.ide.finish import TOOL
from service.events import EventType

REF = {"ide_context": {"repository_id": "private", "generation": "a" * 64}}
REPORT = "В проекте пока нет файлов. Какую структуру создать: src, tests и docs или другую?"
REPLY = "Проект сейчас пустой. Хочешь ли ты создать базовую структуру проекта?"


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["tool", "ignored", "invalid", "failure"])
async def test_prose_terminal_gets_one_metered_finish_only_round(monkeypatch, completion):
    calls = []

    async def toolset(*args):
        return ToolSet(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": TOOL.name,
                        "description": TOOL.description,
                        "parameters": TOOL.params_json_schema,
                    },
                }
            ]
        )

    async def stream(*, messages, tools, round_state, tool_choice=None, **kwargs):
        calls.append((messages, tools, tool_choice))
        round_state.update({"prompt": 10, "completion": 5, "total": 15})
        if len(calls) == 1:
            yield REPLY
        elif completion == "failure":
            raise RuntimeError("private provider error")
        elif completion == "ignored":
            yield "Не показывать этот текст вместо итога"
        else:
            round_state.update(
                {
                    "tool_calls": [
                        {"id": "wrong", "name": "ide_write_file", "arguments": "{}"},
                        {
                            "id": "finish",
                            "name": TOOL.name,
                            "arguments": json.dumps(
                                {
                                    "summary": REPORT if completion == "tool" else "x" * 281,
                                    "outcome": "unchanged",
                                }
                            ),
                        },
                    ]
                }
            )

    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    agent = GeneralAgent({"model": "test-model"})
    monkeypatch.setattr(agent, "_resolve_toolset", toolset)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = [event async for event in agent._run_chat_streamed("Объясни структуру", None)]
        assert execution.workspace.ide_summary == (REPORT if completion == "tool" else None)
        assert not execution.workspace.ide_writes
    assert len(calls) == 2
    assert [tool["function"]["name"] for tool in calls[-1][1]] == [TOOL.name]
    assert calls[-1][2] == {"type": "function", "function": {"name": TOOL.name}}
    assert "".join(event.data for event in events if event.type == EventType.STREAM_CHUNK) == REPLY
    completed = next(event for event in events if event.type == EventType.AGENT_COMPLETE)
    assert completed.metadata["token_usage"]["total"] == (15 if completion == "failure" else 30)
    executed = [event for event in events if event.type == EventType.TOOL_CALL_START]
    assert len(executed) == (1 if completion in {"tool", "invalid"} else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("private,authorized", [(False, True), (True, False)])
async def test_finish_repair_cannot_authorize_a_tool_or_escape_ide(
    monkeypatch, private, authorized
):
    count = 0

    async def toolset(*args):
        return ToolSet(
            tools=[{"type": "function", "function": {"name": TOOL.name}}] if authorized else []
        )

    async def stream(**kwargs):
        nonlocal count
        count += 1
        yield REPLY

    agent = GeneralAgent({"model": "test-model"})
    monkeypatch.setattr(agent, "_resolve_toolset", toolset)
    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    with use_run_execution(PrivateRunResources(workspace_ref=REF if private else None)):
        events = [event async for event in agent._run_chat_streamed("hello", None)]
    assert count == 1
    assert any(event.type == EventType.AGENT_COMPLETE for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["complete", "cancelled", "deadline", "budget"])
async def test_finish_repair_respects_existing_result_and_run_limits(monkeypatch, stop):
    count = 0
    expiring = False

    async def toolset(*args):
        return ToolSet(tools=[{"type": "function", "function": {"name": TOOL.name}}])

    async def stream(**kwargs):
        nonlocal count, expiring
        count += 1
        yield REPLY
        if stop == "complete":
            execution.workspace.ide_summary = REPORT
        if stop == "cancelled":
            execution.cancel()
        expiring = stop == "deadline"

    agent = GeneralAgent({"model": "test-model"})
    monkeypatch.setattr(agent, "_resolve_toolset", toolset)
    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr("service.shared.deadline.must_finalize", lambda: expiring)
    if stop == "budget":
        monkeypatch.setattr(
            "service.domain.runners.chat.preparation.prompt_budget_per_run", lambda: 1000
        )
        monkeypatch.setattr(chat_run, "_estimated_prompt_tokens", lambda *args: 600)
    with use_run_execution(PrivateRunResources(workspace_ref=REF)) as execution:
        events = [event async for event in agent._run_chat_streamed("hello", None)]
    assert count == 1
    assert any(event.type == EventType.AGENT_COMPLETE for event in events)
