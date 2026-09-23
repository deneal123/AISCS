"""Regression coverage for progressive tool disclosure (S11)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from service.domain.capabilities.tool_disclosure import (
    DisclosureResult,
    build_manifest,
    disclose,
    usage_event,
)
from service.domain.capabilities.tool_spec import NOT_IN_TIER, ToolSet
from service.shared.deadline import RunDeadline, use_deadline


def _tools(count: int = 15) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": f"tool_{number}",
                "description": f"Краткое назначение инструмента {number}",
                "parameters": {"type": "object", "properties": {"secret": {"type": "string"}}},
            },
        }
        for number in range(count)
    ]


def _context(user_id: int = 7):
    return SimpleNamespace(
        user_id=user_id,
        workspace_tools_enabled=True,
        tabular_files=[],
        repo_graph_ids=[],
        web_tool_enabled=False,
    )


def _overlay(monkeypatch, *, mode: str = "enforce", canary: str = "", minimum: int = 15):
    from service.shared.agent_settings import runtime_settings

    values = {
        "tool_disclosure_mode": mode,
        "tool_disclosure_min_candidate_count": minimum,
        "tool_disclosure_timeout_sec": 3.0,
        "tool_disclosure_canary_user_ids": canary,
    }
    monkeypatch.setattr(
        runtime_settings, "get_agents", lambda name, default=None: values.get(name, default)
    )


def _response(content: str, *, prompt: int = 12, completion: int = 4):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
        ),
    )


def test_manifest_drops_schemas_and_keeps_compact_hints():
    manifest = build_manifest(_tools(1))

    assert manifest == [
        {"name": "tool_0", "source": "native", "hint": "Краткое назначение инструмента 0"}
    ]
    assert "parameters" not in str(manifest)
    assert "secret" not in str(manifest)


@pytest.mark.asyncio
async def test_enforce_selects_strict_subset_and_reports_tier(monkeypatch):
    _overlay(monkeypatch)
    import service.domain.client as client

    async def models():
        return ["gpt-4o-mini"]

    async def completion(**_kwargs):
        return _response('{"tools":["tool_1","tool_4"]}')

    monkeypatch.setattr(client, "list_qualified_models", models)
    monkeypatch.setattr(client, "create_chat_completion", completion)

    result = await disclose(
        ToolSet(tools=_tools()),
        question="Сравни данные и подготовь файл",
        agent_name="general",
        context=_context(),
        preferred_model="gpt-4o-mini",
        stage=1,
        executed=[],
    )

    assert [tool["function"]["name"] for tool in result.toolset.tools] == ["tool_1", "tool_4"]
    assert {item.reason for item in result.toolset.omissions} == {NOT_IN_TIER}
    disclosure = result.event.metadata["tool_disclosure"]
    assert {key: value for key, value in disclosure.items() if key != "schema_tokens_saved"} == {
        "mode": "enforce",
        "stage": 1,
        "candidates": 15,
        "selected": 2,
        "offered": 2,
        "enforced": True,
    }
    assert disclosure["schema_tokens_saved"] > 0
    assert usage_event(result.usage, "general").metadata["token_usage"]["total"] == 16


@pytest.mark.asyncio
async def test_empty_selection_is_valid_not_a_fallback(monkeypatch):
    _overlay(monkeypatch)
    import service.domain.client as client

    monkeypatch.setattr(client, "list_qualified_models", lambda: _async(["gpt-4o-mini"]))
    monkeypatch.setattr(
        client, "create_chat_completion", lambda **_kwargs: _async(_response('{"tools":[]}'))
    )

    result = await disclose(
        ToolSet(tools=_tools()),
        question="Привет",
        agent_name="general",
        context=_context(),
        preferred_model="gpt-4o-mini",
        stage=1,
        executed=[],
    )

    assert result.toolset.tools == []
    assert result.event.metadata["tool_disclosure"].get("fallback_reason") is None


@pytest.mark.asyncio
async def test_invalid_selector_answer_falls_back_to_original_toolset(monkeypatch):
    _overlay(monkeypatch)
    import service.domain.client as client

    monkeypatch.setattr(client, "list_qualified_models", lambda: _async(["gpt-4o-mini"]))
    monkeypatch.setattr(
        client,
        "create_chat_completion",
        lambda **_kwargs: _async(_response('{"tools":["tool_0","not_allowed"]}')),
    )
    original = ToolSet(tools=_tools())

    result = await disclose(
        original,
        question="Нужен инструмент",
        agent_name="general",
        context=_context(),
        preferred_model="gpt-4o-mini",
        stage=2,
        executed=[{"tool": "tool_1", "status": "succeeded"}],
    )

    assert result.toolset is original
    assert result.event.metadata["tool_disclosure"]["fallback_reason"] == "invalid_selection"
    assert result.usage["total"] == 16


@pytest.mark.asyncio
async def test_observe_and_canary_preserve_original_set(monkeypatch):
    _overlay(monkeypatch, mode="observe", canary="8")
    import service.domain.client as client

    calls = 0

    async def completion(**_kwargs):
        nonlocal calls
        calls += 1
        return _response('{"tools":["tool_0"]}')

    monkeypatch.setattr(client, "list_qualified_models", lambda: _async(["gpt-4o-mini"]))
    monkeypatch.setattr(client, "create_chat_completion", completion)
    original = ToolSet(tools=_tools())

    skipped = await disclose(
        original,
        question="x",
        agent_name="general",
        context=_context(7),
        preferred_model="gpt-4o-mini",
        stage=1,
        executed=[],
    )
    observed = await disclose(
        original,
        question="x",
        agent_name="general",
        context=_context(8),
        preferred_model="gpt-4o-mini",
        stage=1,
        executed=[],
    )

    assert skipped.event is None and calls == 1
    assert observed.toolset is original
    assert observed.event.metadata["tool_disclosure"]["selected"] == 1


@pytest.mark.asyncio
async def test_deadline_fallback_does_not_call_selector(monkeypatch):
    _overlay(monkeypatch)
    import service.domain.client as client

    async def unexpected(**_kwargs):
        raise AssertionError("selector must not run inside finalization reserve")

    monkeypatch.setattr(client, "create_chat_completion", unexpected)
    original = ToolSet(tools=_tools())
    expired = RunDeadline(started_monotonic=0.0, limit_sec=0.001, finalization_reserve_sec=0.0)
    with use_deadline(expired):
        result = await disclose(
            original,
            question="x",
            agent_name="general",
            context=_context(),
            preferred_model="gpt-4o-mini",
            stage=1,
            executed=[],
        )

    assert result.toolset is original
    assert result.event.metadata["tool_disclosure"]["fallback_reason"] == "deadline"


@pytest.mark.asyncio
async def test_prompt_budget_fallback_does_not_call_selector(monkeypatch):
    _overlay(monkeypatch)
    import service.domain.client as client

    async def unexpected(**_kwargs):
        raise AssertionError("selector must not run when its prompt exceeds the run budget")

    monkeypatch.setattr(client, "create_chat_completion", unexpected)
    original = ToolSet(tools=_tools())

    result = await disclose(
        original,
        question="Нужен подробный разбор набора данных",
        agent_name="general",
        context=_context(),
        preferred_model="gpt-4o-mini",
        stage=1,
        executed=[],
        remaining_prompt_tokens=1,
    )

    assert result.toolset is original
    assert result.usage is None
    assert result.event.metadata["tool_disclosure"]["fallback_reason"] == "prompt_budget"


@pytest.mark.asyncio
async def test_chat_runner_reselects_after_a_completed_tool_round(monkeypatch):
    """The second tier sees only completed tool names/statuses, never raw output."""
    from service.domain import base as base_mod
    from service.domain.runners import chat_run as chat_runner
    from service.domain.subagents.general import GeneralAgent
    from service.schemas.agents import UserContext

    stages: list[tuple[int, list[dict[str, str]]]] = []
    calls = 0

    async def fake_disclose(toolset, **kwargs):
        stages.append((kwargs["stage"], kwargs["executed"]))
        return DisclosureResult(toolset)

    async def fake_stream(*, round_state=None, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            round_state.update(
                {
                    "tool_calls": [{"id": "call_1", "name": "tool_0", "arguments": "{}"}],
                    "finish_reason": "tool_calls",
                }
            )
            return
        round_state.update({"prompt": 5, "completion": 2, "total": 7, "finish_reason": "stop"})
        yield "Готово"

    async def fake_toolset(self, _model, _context=None):
        return ToolSet(tools=_tools())

    from service.domain.runners import tool_disclosure_state

    monkeypatch.setattr(tool_disclosure_state, "disclose", fake_disclose)
    monkeypatch.setattr(chat_runner, "stream_chat_completion", fake_stream)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", fake_toolset)
    agent = GeneralAgent({"model": "test-model"})
    context = UserContext(user_id="7", request_time=datetime.now(UTC))

    events = [event async for event in agent._run_chat_streamed("проверь", context)]

    assert [stage for stage, _executed in stages] == [1, 2]
    assert stages[1][1] == [{"tool": "tool_0", "status": "failed"}]
    assert any(event.data == "Готово" for event in events)


async def _async(value):
    return value
