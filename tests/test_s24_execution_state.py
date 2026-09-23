"""Deterministic S24 contracts for run state, grounding, and revisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from service.application.reply_assembler import ReplyAssembler
from service.domain.capabilities.tool_disclosure import disclose
from service.domain.capabilities.tool_spec import ToolSet
from service.domain.integration_failure import IntegrationFailureCode
from service.domain.run_context import (
    GroundingRequirement,
    PrivateRunResources,
    prompt_safe_context_payload,
    set_policy_flag,
    tool_context_payload,
    use_run_execution,
)
from service.domain.runners.tool_runtime import ToolCallOutcome, execute_tool_calls
from service.domain.subagents.runtime import StageContext
from service.domain.tools import workspace_client
from service.domain.tools.workspace_client import WorkspaceUnavailable
from service.domain.usage_ledger import UsageKind, receipt_from_usage
from service.events import AgentEvent, EventType
from service.schemas.agents import UserContext


def _serialized_tool(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "Synthetic safe tool.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }


def _selector_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2, total_tokens=9),
    )


def _selector_settings(monkeypatch, *, mode: str = "off") -> None:
    from service.shared.agent_settings import runtime_settings

    values = {
        "tool_disclosure_mode": mode,
        "tool_disclosure_min_candidate_count": 15,
        "tool_disclosure_timeout_sec": 3.0,
        "tool_disclosure_canary_user_ids": "",
    }
    monkeypatch.setattr(
        runtime_settings,
        "get_agents",
        lambda name, default=None: values.get(name, default),
    )


@pytest.mark.asyncio
async def test_required_grounding_selects_below_s11_threshold_and_forces_once(monkeypatch) -> None:
    _selector_settings(monkeypatch, mode="off")
    from service.domain import client

    calls = 0

    async def models():
        return ["answer-model"]

    async def completion(**_kwargs):
        nonlocal calls
        calls += 1
        return _selector_response('{"tools":["ws_read"],"preferred_tool":"ws_read"}')

    monkeypatch.setattr(client, "list_qualified_models", models)
    monkeypatch.setattr(client, "create_chat_completion", completion)
    context = SimpleNamespace(
        user_id="synthetic",
        workspace_tools_enabled=True,
        web_tool_enabled=False,
        tabular_files=[],
        repo_graph_ids=[],
    )
    toolset = ToolSet(tools=[_serialized_tool("ws_read"), _serialized_tool("ws_list")])

    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
        result = await disclose(
            toolset,
            question="synthetic request",
            agent_name="general",
            context=context,
            preferred_model="answer-model",
            stage=1,
            executed=[],
        )

        assert calls == 1
        assert result.toolset is toolset  # mode=off preserves the authorized set
        assert result.preferred_tool == "ws_read"
        assert result.grounding_required is True
        intent = result.intent_event.metadata["tool_intent"]
        assert intent == {
            "required": True,
            "forced": True,
            "candidates": 2,
            "offered": 2,
            "reason": "workspace_explicit",
        }
        assert "ws_read" not in str(intent)
        assert [receipt.kind for receipt in execution.usage.receipts] == ["tool_selector"]
        assert execution.provider_session.pinned_provider is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "fallback"),
    [
        ('{"tools":[],"preferred_tool":null}', "empty_selection"),
        ('{"tools":["ws_read"],"preferred_tool":"not_allowed"}', "invalid_selection"),
    ],
)
async def test_grounding_degradation_never_removes_authorized_tools(
    monkeypatch, answer: str, fallback: str
) -> None:
    _selector_settings(monkeypatch, mode="enforce")
    from service.domain import client

    async def models():
        return ["answer-model"]

    async def completion(**_kwargs):
        return _selector_response(answer)

    monkeypatch.setattr(client, "list_qualified_models", models)
    monkeypatch.setattr(client, "create_chat_completion", completion)
    original = ToolSet(tools=[_serialized_tool("ws_read")])
    context = SimpleNamespace(user_id="synthetic")

    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
        result = await disclose(
            original,
            question="synthetic request",
            agent_name="general",
            context=context,
            preferred_model="answer-model",
            stage=1,
            executed=[],
        )

    assert result.toolset is original
    assert result.preferred_tool is None
    assert result.event.metadata["tool_disclosure"]["fallback_reason"] == fallback
    assert result.intent_event.metadata["tool_intent"]["forced"] is False


def test_private_capabilities_are_not_prompt_context_or_policy_mutations() -> None:
    marker = "S24_PRIVATE_CAPABILITY"
    context = UserContext(
        user_id="synthetic",
        request_time=datetime.now(UTC),
        workspace_ref={"token": marker},
        tabular_files=[{"url": marker}],
        reference_image_url=marker,
    )
    resources = PrivateRunResources.from_request(
        workspace_ref={"token": marker},
        tabular_files=[{"url": marker}],
        reference_image_url=marker,
    )

    with use_run_execution(resources) as execution:
        set_policy_flag(context, "workspace_tools_enabled", True)
        safe = prompt_safe_context_payload(context)
        workspace_projection = tool_context_payload(context, "ws_read")
        table_projection = tool_context_payload(context, "analyze_data")

        assert execution.policy.flag("workspace_tools_enabled") is True
        assert context.workspace_tools_enabled is False
        assert marker not in str(safe)
        assert workspace_projection["workspace_ref"]["token"] == marker
        assert "tabular_files" not in workspace_projection
        assert table_projection["tabular_files"][0]["url"] == marker
        assert "workspace_ref" not in table_projection


def test_stage_runtime_and_provider_session_share_one_idempotent_ledger() -> None:
    with use_run_execution(PrivateRunResources()) as execution:
        stage = StageContext()
        assert stage.usage is execution.usage
        execution.provider_session.complete_round(
            provider="provider-a",
            model="answer-a",
            usage={"prompt": 10, "completion": 3},
            kind=UsageKind.CHAT,
            call_id="chat-1",
        )
        stage.usage.record(
            receipt_from_usage(
                {"prompt": 4, "completion": 1},
                provider="provider-b",
                model="meta-b",
                kind=UsageKind.TOOL_SELECTOR,
                receipt_id="selector-1",
            )
        )
        assembler = ReplyAssembler(execution.usage)
        event = AgentEvent(
            type=EventType.STATUS_UPDATE,
            data="",
            metadata={
                "kind": "meta_usage",
                "token_usage": {
                    "prompt": 10,
                    "completion": 3,
                    "calls": [execution.usage.get("chat-1").as_dict()],
                },
            },
        )
        for _ in range(2):
            assembler.consume(
                event=event,
                stream_chunk_type=EventType.STREAM_CHUNK,
                error_type=EventType.ERROR,
                structured_output_type=EventType.STRUCTURED_OUTPUT,
            )
        assembler.finalize_usage()

        assert assembler.prompt_tokens == 14
        assert assembler.completion_tokens == 4
        assert [
            (call["provider"], call["model"], call["kind"]) for call in assembler.per_call_usage
        ] == [
            ("provider-a", "answer-a", "chat"),
            ("provider-b", "meta-b", "tool_selector"),
        ]
        assert "usage_integrity" not in assembler.metadata


def test_missing_usage_provenance_is_bounded_without_dropping_cost() -> None:
    with use_run_execution(PrivateRunResources()) as execution:
        execution.usage.record_usage(
            {"prompt": 5, "completion": 2},
            model=None,
            provider=None,
            kind=UsageKind.CHAT,
            receipt_id="missing-provenance",
        )
        assembler = ReplyAssembler(execution.usage)
        assembler.finalize_usage()

        assert assembler.total_tokens == 7
        assert assembler.metadata["usage_integrity"] == {
            "anomaly_count": 2,
            "reason_codes": ["missing_model", "missing_provider"],
        }


@pytest.mark.asyncio
async def test_workspace_conflict_requires_explicit_read_before_next_mutation(monkeypatch) -> None:
    seen: list[tuple[str, dict]] = []
    write_attempts = 0

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, json, headers):
            nonlocal write_attempts
            path = str(url)
            seen.append((path, dict(json)))
            if path.endswith("/view"):
                return httpx.Response(200, json={"revision": "r1"})
            if path.endswith("/files/read"):
                return httpx.Response(200, json={"content": "new", "revision": "r2"})
            if path.endswith("/files/write"):
                write_attempts += 1
                if write_attempts == 1:
                    return httpx.Response(409, json={"error": "workspace_conflict"})
                return httpx.Response(200, json={"revision": "r3", "written": True})
            raise AssertionError("unexpected endpoint")

    monkeypatch.setattr(workspace_client, "_settings", lambda: ("http://workspace", 30.0, True))
    monkeypatch.setattr(workspace_client.httpx, "AsyncClient", Client)
    ref = {
        "workspace_id": "workspace",
        "user_id": "user",
        "token": "opaque",
        "coordination_capability": "opaque-capability",
    }

    with use_run_execution(PrivateRunResources(workspace_ref=ref)) as execution:
        with pytest.raises(WorkspaceUnavailable) as first:
            await workspace_client.call(ref, "files/write", {"path": "a", "content": "mine"})
        assert first.value.code is IntegrationFailureCode.CONFLICT
        calls_after_conflict = len(seen)

        with pytest.raises(WorkspaceUnavailable) as blocked:
            await workspace_client.call(ref, "files/write", {"path": "a", "content": "mine"})
        assert blocked.value.code is IntegrationFailureCode.CONFLICT
        assert len(seen) == calls_after_conflict
        assert execution.workspace.requires_read is True

        await workspace_client.call(ref, "files/read", {"path": "a"})
        assert execution.workspace.revision == "r2"
        assert execution.workspace.requires_read is False
        await workspace_client.call(ref, "files/write", {"path": "a", "content": "revised"})

    last_write = [payload for path, payload in seen if path.endswith("/files/write")][-1]
    assert last_write["expected_revision"] == "r2"


@pytest.mark.asyncio
async def test_workspace_mutations_are_serialized_but_reads_remain_parallel() -> None:
    active = 0
    maximum = 0
    order: list[str] = []

    async def invoke(_tool, _context, arguments):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        order.append(f"start:{arguments}")
        await asyncio.sleep(0)
        order.append(f"end:{arguments}")
        active -= 1
        return ToolCallOutcome("ok", "succeeded", 0.0)

    tools = {name: _serialized_tool(name) for name in ("mutate_a", "mutate_b")}
    calls = [
        {"id": "a", "name": "mutate_a", "arguments": "{}"},
        {"id": "b", "name": "mutate_b", "arguments": "{}"},
    ]
    await execute_tool_calls(
        calls,
        tools,
        None,
        concurrency=2,
        invoker=invoke,
        concurrency_group=lambda _name: "workspace",
    )

    assert maximum == 1
    assert order == ["start:{}", "end:{}", "start:{}", "end:{}"]

    active = maximum = 0
    await execute_tool_calls(
        calls,
        tools,
        None,
        concurrency=2,
        invoker=invoke,
        concurrency_group=lambda _name: None,
    )
    assert maximum == 2
