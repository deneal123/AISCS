import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.application.agent_execution_service import _finalize_reply
from service.application.human_questions.admission import apply_human_question_context
from service.application.reply_assembler import ReplyAssembler
from service.domain.capabilities.tools.spec import ToolSet
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.chat import run as chat_run
from service.domain.runners.support import _tools_to_openai
from service.domain.runners.tool_runtime import ToolCallOutcome
from service.domain.subagents.general import GeneralAgent
from service.domain.tools.human_question_tool import SPEC, TOOL, ask_user_question
from service.events import EventType
from service.shared.human_question import resume_question_continuation

PROMPT = {
    "prompt": "Какую структуру добавить?",
    "choices": [{"id": "basic", "label": "src и tests"}, {"id": "docs", "label": "Только docs"}],
}


@pytest.mark.asyncio
async def test_local_question_requires_server_gate_and_is_run_scoped_and_unbilled():
    assert SPEC.billing_name is None and not SPEC.dedup_safe
    with use_run_execution(PrivateRunResources()) as execution:
        assert isinstance(await ask_user_question(None, json.dumps(PROMPT)), ToolCallOutcome)
        assert execution.question.prompt is None
        execution.policy.set_flag("human_questions_enabled", True)
        assert json.loads(await ask_user_question(None, json.dumps(PROMPT))) == {
            "awaiting_user": True
        }
        previous = execution.question.prompt
        assert isinstance(await ask_user_question(None, json.dumps(PROMPT)), ToolCallOutcome)
        assert execution.question.prompt is previous and not execution.question.waiting
        assert PROMPT["prompt"] not in repr(execution.question)
    with use_run_execution(PrivateRunResources()) as execution:
        assert execution.question.prompt is None


@pytest.mark.parametrize("surface", ["ide", "pdf"])
@pytest.mark.parametrize("enabled", [False, True, 1])
@pytest.mark.parametrize(
    "provider", ["mws", "openrouter", "gigachat", "routerai", "openai", "local"]
)
def test_admission_requires_private_capability_existing_target_and_streamed_provider(
    surface, enabled, provider
):
    target = {"repository_id": str(uuid4())} if surface == "ide" else {"project_id": str(uuid4())}
    ref = {
        f"{'document' if surface == 'pdf' else 'ide'}_context": target,
        "human_questions_enabled": enabled,
    }
    with use_run_execution(PrivateRunResources(workspace_ref=ref)) as execution:
        execution.provider_admission = SimpleNamespace(
            snapshot=SimpleNamespace(active_provider=provider, release=lambda: None)
        )
        assert apply_human_question_context(execution) is (enabled is True)
        execution.provider_admission.snapshot.active_provider = "unsupported-sdk"
        assert not apply_human_question_context(execution)


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ide", "pdf"])
async def test_stream_parks_after_question_without_finish_round_or_public_transcript(
    monkeypatch, surface
):
    writes, provider_calls = [], []
    ref = {"token": "PRIVATE-CAPABILITY"}
    ref["ide_context" if surface == "ide" else "document_context"] = {
        "repository_id" if surface == "ide" else "project_id": str(uuid4()),
        "generation": "a" * 64,
    }

    async def acknowledge(_ref, endpoint, payload):
        writes.append(endpoint)
        return {
            "written": True,
            "path": payload["path"],
            "kind": "file",
            "size": len(payload["content"].encode()),
            "digest": hashlib.sha256(payload["content"].encode()).hexdigest(),
        }

    async def stream(*, round_state, **kwargs):
        provider_calls.append(kwargs)
        round_state.update(
            {"prompt": 10, "completion": 5, "total": 15, "finish_reason": "tool_calls"}
        )
        writing = surface == "ide" and len(provider_calls) == 1
        round_state.update(
            {
                "tool_calls": [
                    {
                        "id": "write" if writing else "question",
                        "name": "ide_write_file" if writing else TOOL.name,
                        "arguments": json.dumps(
                            {"path": "README.md", "content": "PRIVATE-SOURCE", "base_digest": ""}
                            if writing
                            else PROMPT
                        ),
                    }
                ]
            }
        )
        if False:
            yield ""

    async def toolset(*_args):
        from service.domain.tools.ide.tools import TOOLS

        return ToolSet(
            tools=_tools_to_openai(
                [TOOL, *[tool for tool in TOOLS if tool.name == "ide_write_file"]]
            )
        )

    async def forbidden_inventory(*_args):
        raise AssertionError("pause_must_not_materialize_artifacts")

    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr("service.domain.tools.ide.tools.call", acknowledge)
    monkeypatch.setattr(
        "service.application.agent_execution_service._workspace_artifacts", forbidden_inventory
    )
    agent = GeneralAgent({"model": "test-model"})
    monkeypatch.setattr(agent, "_resolve_toolset", toolset)

    async def unexpected_failure(error, **_kwargs):
        raise AssertionError(type(error).__name__) from error
        if False:
            yield None

    monkeypatch.setattr(agent, "_interrupted", unexpected_failure)
    with use_run_execution(PrivateRunResources(workspace_ref=ref)) as execution:
        execution.policy.set_flag("human_questions_enabled", True)
        events = [
            event
            async for event in agent._run_chat_streamed("Добавь README и уточни структуру", None)
        ]
        assert execution.question.waiting
        assert not any(
            event.type in {EventType.ERROR, EventType.AGENT_COMPLETE} for event in events
        )
        assembler = ReplyAssembler(execution.usage)
        for event in events:
            assembler.consume(
                event=event,
                stream_chunk_type=EventType.STREAM_CHUNK,
                error_type=EventType.ERROR,
                structured_output_type=EventType.STRUCTURED_OUTPUT,
            )
        result = await _finalize_reply(
            reply_assembler=assembler,
            metadata={},
            workspace_ref=ref,
            resolved_model="test-model",
            timings=SimpleNamespace(as_meta=lambda: {}),
        )
        assert result["metadata"]["execution_status"] == "waiting_user"
        assert result["metadata"]["awaiting_user"] is True
        assert "ide_summary" not in result["metadata"]
        assert "PRIVATE" not in json.dumps(result["metadata"])
        assert "PRIVATE" not in json.dumps([event.model_dump() for event in events])
        pause = result["_human_question_pause_v1"]
        resumed = resume_question_continuation(
            pause["continuation"], execution.question.prompt, {"choice_id": "basic", "text": None}
        )
        assert resumed["messages"][:-1] == pause["continuation"]["messages"][:-1]
        assert result["total_tokens"] == len(provider_calls) * 15
    assert len(provider_calls) == (2 if surface == "ide" else 1)
    assert writes == (["ide/agent/write"] if surface == "ide" else [])


@pytest.mark.asyncio
async def test_mixed_question_and_write_batch_executes_neither_tool(monkeypatch):
    async def forbidden(*args):
        raise AssertionError("mixed_batch_must_not_invoke")

    monkeypatch.setattr("service.domain.tools.ide.tools.call", forbidden)
    from service.domain.tools.ide.tools import TOOLS

    write = next(tool for tool in TOOLS if tool.name == "ide_write_file")
    calls = [
        {"id": "question", "name": TOOL.name, "arguments": json.dumps(PROMPT)},
        {
            "id": "write",
            "name": write.name,
            "arguments": json.dumps({"path": "x", "content": "x", "base_digest": ""}),
        },
    ]
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("human_questions_enabled", True)
        convo = []
        events = [
            event
            async for event in GeneralAgent({"model": "test-model"})._execute_tool_round(
                convo, calls, {TOOL.name: TOOL, write.name: write}, None, "", set()
            )
        ]
        assert execution.question.prompt is None
        assert len([event for event in events if event.type == EventType.TOOL_CALL_COMPLETE]) == 2
        assert all(
            json.loads(message["content"])["error"] == "question_requires_separate_round"
            for message in convo
            if message["role"] == "tool"
        )


@pytest.mark.asyncio
async def test_stop_before_freezing_never_leaves_a_waiting_question():
    from service.domain.runners.human_question_pause import freeze_pause

    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("human_questions_enabled", True)
        await ask_user_question(None, json.dumps(PROMPT))
        execution.cancel()
        state = SimpleNamespace(execution=execution)
        assert freeze_pause(state, [{"id": "q", "name": TOOL.name}])
        assert execution.question.prompt is None and not execution.question.waiting


@pytest.mark.asyncio
async def test_unfreezable_transcript_stops_with_closed_error_instead_of_polling():
    from service.domain.runners.human_question_pause import freeze_pause, question_boundary_event

    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.set_flag("human_questions_enabled", True)
        await ask_user_question(None, json.dumps(PROMPT))
        state = SimpleNamespace(
            execution=execution,
            model="test-model",
            segment="",
            convo=[{"role": "user", "content": "PRIVATE-SOURCE"}],
        )
        assert freeze_pause(state, [{"id": "q", "name": TOOL.name}])
        assert execution.question.failed and not execution.question.waiting
        event = question_boundary_event(execution, agent_name="general", usage={"total": 15})
        assert event.type == EventType.ERROR and event.metadata["failure_code"] == "payload"
        assert "PRIVATE" not in event.model_dump_json()
