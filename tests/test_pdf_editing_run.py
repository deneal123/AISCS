"""An owned PDF edit reaches the real tool loop without a planner file decision."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.application.admission.document_tools import apply_document_tool_consent
from service.application.agent_execution_service import _finalize_reply
from service.application.reply_assembler import ReplyAssembler
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.execution.documents import DOCUMENT_EDITING_INSTRUCTIONS
from service.domain.runners.chat import run as chat_run
from service.domain.subagents.general import GeneralAgent
from service.domain.tools import document_proposal_tool
from service.events import EventType
from service.schemas.agents import UserContext


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_invalid_block", [False, True])
async def test_first_cat_slide_produces_reviewable_patch_not_just_chat_text(
    monkeypatch, repair_invalid_block
):
    draft = {
        "schema_version": 1,
        "version": 1,
        "title": "Презентация",
        "blocks": [
            {"block_id": "slide_1", "kind": "slide", "title": "Первый слайд", "text": "Шаблон"},
            {"block_id": "slide_2", "kind": "slide", "title": "Далее", "text": "Не менять"},
        ],
    }
    target = {
        "path": "documents/slides",
        "project_id": "owned-project",
        "expected_revision": "r1",
        "draft_digest": "a" * 64,
        "tools_auto_approved": True,
        "content": json.dumps(draft),
    }
    ref = {
        "workspace_id": "owned-workspace",
        "token": "PRIVATE_CAPABILITY",
        "document_context": target,
    }
    patch = {
        "base_version": 1,
        "replacements": [
            {
                "block_id": "slide_1",
                "kind": "slide",
                "title": "Мир котиков",
                "text": "Пушистые друзья рядом с нами",
                "items": [],
                "columns": [],
                "rows": [],
                "source_id": 0,
                "asset_path": "",
                "level": 1,
            },
        ],
    }
    proposal = AsyncMock(return_value={"proposal_id": "b" * 32})
    monkeypatch.setattr(document_proposal_tool, "call", proposal)
    monkeypatch.setattr(
        "service.shared.model_catalog.model_supports_tools", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        "service.application.agent_execution_service._workspace_artifacts",
        AsyncMock(return_value=[]),
    )
    rounds = []

    async def stream(*, messages, tools, model, round_state, **kwargs):
        rounds.append(messages)
        assert DOCUMENT_EDITING_INSTRUCTIONS in messages[0]["content"]
        assert "PRIVATE_CAPABILITY" not in json.dumps(messages)
        assert "tex_propose_patch" in {tool["function"]["name"] for tool in tools}
        round_state.update({"model": model, "prompt": 20, "completion": 10, "total": 30})
        if len(rounds) <= (2 if repair_invalid_block else 1):
            arguments = json.loads(json.dumps(patch))
            if repair_invalid_block and len(rounds) == 1:
                arguments["replacements"][0]["block_id"] = "invented_slide"
            elif repair_invalid_block:
                feedback = json.loads(messages[-1]["content"])
                assert feedback["error_code"] == "unknown_block_id"
                assert "block_id" in feedback["message"]
                assert proposal.await_count == 0
            round_state.update(
                {
                    "finish_reason": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "patch-1",
                            "name": "tex_propose_patch",
                            "arguments": json.dumps(arguments),
                        },
                    ],
                }
            )
        else:
            assert json.loads(messages[-1]["content"])["status"] == "awaiting_review"
            round_state["finish_reason"] = "stop"
            yield "Правки первого слайда готовы к просмотру и применению."

    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    context = UserContext(user_id="owner", request_time=datetime.now(UTC))
    with use_run_execution(PrivateRunResources(workspace_ref=ref)) as execution:
        assert apply_document_tool_consent(execution)
        agent = GeneralAgent({"model": "test-model"})
        assembler = ReplyAssembler(execution.usage)
        events = [
            event
            async for event in agent._run_chat_streamed(
                "Презентация о котиках, создай черновик первого слайда", context
            )
        ]
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
            timings=SimpleNamespace(as_meta=lambda: {}),
            workspace_ref=ref,
            resolved_model="test-model",
        )
        assert not execution.policy.flag("workspace_tools_enabled")
    assert len(rounds) == (3 if repair_invalid_block else 2)
    assert proposal.await_count == 1, rounds[-1][-1]
    proposal.assert_awaited_once()
    assert proposal.call_args.args[1] == "documents/proposals"
    payload = proposal.call_args.args[2]
    assert payload["path"] == "documents/slides"
    assert payload["expected_revision"] == "r1"
    assert [block["block_id"] for block in payload["proposal"]["replacements"]] == ["slide_1"]
    assert payload["proposal"]["replacements"][0]["title"] == "Мир котиков"
    assert draft["blocks"][0]["text"] == "Шаблон"  # Nothing applied before review.
    assert result["metadata"]["document_proposal"] == "b" * 32
    assert result["metadata"]["document_project"] == "owned-project"
    assert "PRIVATE_CAPABILITY" not in str(result)
