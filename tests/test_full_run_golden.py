"""Versioned, deterministic merge gate for complete scripted agent runs.

The corpus exercises the production chat runner with no network, user data, files, or
storage.  Its assertions are deliberately limited to event kinds, bounded metadata and
deterministic budget units; raw prompts, arguments and tool output never become golden
fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from service.domain import base as base_mod
from service.domain.capabilities.tool_spec import ToolSet
from service.domain.run_context import (
    GroundingRequirement,
    PrivateRunResources,
    use_run_execution,
)
from service.domain.runners import chat_run, tool_loop
from service.domain.subagents.general import GeneralAgent
from service.events import AgentEvent, EventSerializer, EventType
from service.schemas.agents import UserContext

CORPUS_VERSION = "s26-v1"
_SENTINEL = "synthetic-request-must-not-enter-trace"
_MANIFEST = Path(__file__).resolve().parent / "fixtures" / "run_quality_s16.json"


@dataclass(frozen=True, slots=True)
class FullRunScenario:
    manifest_id: str
    candidates: int
    disclosure_mode: str
    selector_response: str
    expected_disclosures: int
    expected_meta_usage: int
    expected_schema_saving: bool
    expected_offered: int | None
    expected_fallback_reason: str | None
    expected_order: tuple[str, ...]


FULL_RUN_SCENARIOS = (
    FullRunScenario(
        manifest_id="s11_static_under_fifteen",
        candidates=14,
        disclosure_mode="enforce",
        selector_response='{"tools":[]}',
        expected_disclosures=0,
        expected_meta_usage=0,
        expected_schema_saving=False,
        expected_offered=None,
        expected_fallback_reason=None,
        expected_order=(
            "status:tool_availability",
            "status:tool_plan",
            "tool_call_start",
            "status:tool_progress",
            "tool_call_complete",
            "status:tool_progress",
            "stream_chunk",
            "status:tool_summary",
            "agent_complete",
        ),
    ),
    FullRunScenario(
        manifest_id="s11_enforce_reselection",
        candidates=15,
        disclosure_mode="enforce",
        selector_response='{"tools":["fetch_url"]}',
        expected_disclosures=2,
        expected_meta_usage=2,
        expected_schema_saving=True,
        expected_offered=1,
        expected_fallback_reason=None,
        expected_order=(
            "status:tool_disclosure",
            "status:meta_usage",
            "status:tool_availability",
            "status:tool_omissions",
            "status:tool_plan",
            "tool_call_start",
            "status:tool_progress",
            "tool_call_complete",
            "status:tool_progress",
            "status:tool_disclosure",
            "status:meta_usage",
            "stream_chunk",
            "status:tool_summary",
            "agent_complete",
        ),
    ),
    FullRunScenario(
        manifest_id="s11_observe",
        candidates=15,
        disclosure_mode="observe",
        selector_response='{"tools":["fetch_url"]}',
        expected_disclosures=2,
        expected_meta_usage=2,
        expected_schema_saving=True,
        expected_offered=15,
        expected_fallback_reason=None,
        expected_order=(
            "status:tool_disclosure",
            "status:meta_usage",
            "status:tool_availability",
            "status:tool_plan",
            "tool_call_start",
            "status:tool_progress",
            "tool_call_complete",
            "status:tool_progress",
            "status:tool_disclosure",
            "status:meta_usage",
            "stream_chunk",
            "status:tool_summary",
            "agent_complete",
        ),
    ),
    FullRunScenario(
        manifest_id="s11_selector_fallbacks",
        candidates=15,
        disclosure_mode="enforce",
        selector_response='{"tools":["unavailable"]}',
        expected_disclosures=2,
        expected_meta_usage=2,
        expected_schema_saving=False,
        expected_offered=15,
        expected_fallback_reason="invalid_selection",
        expected_order=(
            "status:tool_disclosure",
            "status:meta_usage",
            "status:tool_availability",
            "status:tool_plan",
            "tool_call_start",
            "status:tool_progress",
            "tool_call_complete",
            "status:tool_progress",
            "status:tool_disclosure",
            "status:meta_usage",
            "stream_chunk",
            "status:tool_summary",
            "agent_complete",
        ),
    ),
)


def _serialized_tools(count: int) -> list[dict]:
    names = ["fetch_url", *[f"golden_tool_{number}" for number in range(1, count)]]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"deterministic golden capability {number}",
                "parameters": {"type": "object", "properties": {"private": {"type": "string"}}},
            },
        }
        for number, name in enumerate(names)
    ]


def _signature(event) -> str:
    if event.type == EventType.STATUS_UPDATE:
        return f"status:{event.metadata.get('kind', '')}"
    return str(getattr(event.type, "value", event.type))


def test_full_run_golden_manifest_is_versioned_and_data_free() -> None:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    scenario_ids = {item["id"] for item in manifest["scenarios"]}

    assert manifest["version"] == CORPUS_VERSION
    assert {scenario.manifest_id for scenario in FULL_RUN_SCENARIOS} <= scenario_ids
    assert _SENTINEL not in str(manifest)
    assert not {"prompt", "arguments", "result", "request_text", "url"} & set(manifest)


def test_full_run_privacy_sentinel_does_not_cross_the_agent_stream_boundary() -> None:
    payload = EventSerializer().serialize(
        event=AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name="router",
            metadata={
                "kind": "mode_offer",
                "mode_offer": {
                    "mode": "deep_research",
                    "prompt": _SENTINEL,
                    "reason": _SENTINEL,
                    "reason_code": "confirmation_required",
                },
            },
        ),
        job_id="synthetic",
    )

    assert payload["metadata"]["mode_offer"] == {
        "mode": "deep_research",
        "reason_code": "confirmation_required",
    }
    assert _SENTINEL not in str(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", FULL_RUN_SCENARIOS, ids=lambda item: item.manifest_id)
async def test_full_run_golden_contract(monkeypatch, scenario: FullRunScenario) -> None:
    """Exact full-run ordering plus model/meta/tool budget invariants stay stable."""
    from service.domain import client as client_mod
    from service.shared.agent_settings import runtime_settings

    settings = {
        "tool_disclosure_mode": scenario.disclosure_mode,
        "tool_disclosure_min_candidate_count": 15,
        "tool_disclosure_timeout_sec": 3.0,
        "tool_disclosure_canary_user_ids": "",
        "tool_dedup_mode": "enforce",
    }
    selector_payloads: list[str] = []
    provider_pins: list[str | None] = []
    model_calls = 0
    invocations = 0
    billed: list[str] = []

    monkeypatch.setattr(
        runtime_settings, "get_agents", lambda name, default=None: settings.get(name, default)
    )

    async def list_models():
        return ["golden-model"]

    async def select(*, messages, **_kwargs):
        selector_payloads.append(str(messages[-1]["content"]))
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Message", (), {"content": scenario.selector_response})()},
                    )
                ],
                "usage": type(
                    "Usage", (), {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}
                )(),
            },
        )()

    async def stream(*, round_state=None, pin_provider=None, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        provider_pins.append(pin_provider)
        if model_calls == 1:
            round_state.update(
                {
                    "provider": "golden-provider",
                    "prompt": 10,
                    "completion": 1,
                    "total": 11,
                    "tool_calls": [
                        {
                            "id": "tool-1",
                            "name": "fetch_url",
                            "arguments": '{"url":"https://example.com"}',
                        }
                    ],
                }
            )
            return
        round_state.update({"prompt": 8, "completion": 3, "total": 11, "model": "golden-model"})
        yield "synthetic final"

    async def resolve_tools(_self, _model, _context=None):
        return ToolSet(tools=_serialized_tools(scenario.candidates))

    async def invoke(_tool, _context, _arguments):
        nonlocal invocations
        invocations += 1
        return "synthetic tool result"

    monkeypatch.setattr(client_mod, "list_qualified_models", list_models)
    monkeypatch.setattr(client_mod, "create_chat_completion", select)
    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", resolve_tools)
    monkeypatch.setattr(
        GeneralAgent,
        "_billable_tools_meta",
        classmethod(lambda _cls, name, _billed: billed.append(name) or {"tool_name": name}),
    )

    context = UserContext(user_id="golden", request_time=datetime.now(UTC))
    events = [
        event
        async for event in GeneralAgent({"model": "golden-model"})._run_chat_streamed(
            _SENTINEL, context
        )
    ]

    signatures = [_signature(event) for event in events]
    disclosure = [
        event.metadata["tool_disclosure"]
        for event in events
        if _signature(event) == "status:tool_disclosure"
    ]
    meta_usage = [event for event in events if _signature(event) == "status:meta_usage"]
    complete = [event for event in events if event.type == EventType.AGENT_COMPLETE]

    assert CORPUS_VERSION == "s26-v1"
    assert model_calls == 2
    assert invocations == len(billed) == 1
    assert provider_pins == [None, "golden-provider"]
    assert signatures == list(scenario.expected_order)
    assert signatures[-2:] == ["status:tool_summary", "agent_complete"]
    assert signatures.count("tool_call_start") == signatures.count("tool_call_complete") == 1
    assert signatures.index("status:tool_availability") < signatures.index("status:tool_plan")
    assert len(disclosure) == scenario.expected_disclosures
    assert len(meta_usage) == scenario.expected_meta_usage
    assert complete[-1].metadata["token_usage"] == {
        "prompt": 18,
        "completion": 4,
        "total": 22,
        "model": "golden-model",
        "provider": "golden-provider",
    }
    assert all(_SENTINEL not in str(event.metadata) for event in events)
    assert all("private" not in str(event.metadata) for event in events)

    if scenario.expected_disclosures:
        assert [item["stage"] for item in disclosure] == [1, 2]
        assert all(item["candidates"] == scenario.candidates for item in disclosure)
        assert (
            all(item["schema_tokens_saved"] > 0 for item in disclosure)
            is scenario.expected_schema_saving
        )
        assert all(item["offered"] == scenario.expected_offered for item in disclosure)
        assert all(
            item.get("fallback_reason") == scenario.expected_fallback_reason for item in disclosure
        )
        assert len(selector_payloads) == 2
        assert (
            '"executed_tools":[{"tool":"fetch_url","status":"succeeded"}]' in selector_payloads[1]
        )
        assert all(
            "arguments" not in payload and "synthetic tool result" not in payload
            for payload in selector_payloads
        )
        availability = next(
            event.metadata["tool_availability"]
            for event in events
            if _signature(event) == "status:tool_availability"
        )
        assert len(availability["offered"]) == scenario.expected_offered
    else:
        assert selector_payloads == []


@pytest.mark.asyncio
async def test_full_run_round_cap_finalizes_without_tool_execution(monkeypatch) -> None:
    """A cap is terminal but preserves the model usage already incurred for the run."""
    from service.domain import client as client_mod

    invocations = 0

    async def list_models():
        return ["golden-model"]

    async def stream(*, round_state=None, **_kwargs):
        if round_state is not None:
            round_state.update(
                {
                    "provider": "golden-provider",
                    "prompt": 7,
                    "completion": 0,
                    "total": 7,
                    "tool_calls": [{"id": "tool-1", "name": "fetch_url", "arguments": "{}"}],
                }
            )
        if False:
            yield "unreachable"

    async def resolve_tools(_self, _model, _context=None):
        return ToolSet(tools=_serialized_tools(1))

    async def invoke(_tool, _context, _arguments):
        nonlocal invocations
        invocations += 1
        return "unreachable"

    monkeypatch.setattr(client_mod, "list_qualified_models", list_models)
    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", resolve_tools)

    agent = GeneralAgent({"model": "golden-model"})
    agent.max_turns = 0
    context = UserContext(user_id="golden", request_time=datetime.now(UTC))
    events = [event async for event in agent._run_chat_streamed("synthetic", context)]

    signatures = [_signature(event) for event in events]
    complete = events[-1]
    assert invocations == 0
    assert signatures == [
        "status:tool_availability",
        "status:tool_progress",
        "stream_chunk",
        "status:tool_summary",
        "agent_complete",
    ]
    assert complete.metadata["tool_cap_reached"] is True
    assert complete.metadata["token_usage"]["total"] == 7


@pytest.mark.asyncio
async def test_s25_grounding_repair_is_a_ledger_native_full_run(monkeypatch) -> None:
    """One missed forced call is repaired without leaking its draft response."""
    from service.domain import client as client_mod
    from service.shared.agent_settings import runtime_settings

    settings = {
        "tool_disclosure_mode": "enforce",
        "tool_disclosure_min_candidate_count": 15,
        "tool_disclosure_timeout_sec": 3.0,
        "tool_disclosure_canary_user_ids": "",
        "tool_dedup_mode": "enforce",
    }
    model_calls = 0
    tool_calls = 0
    choices: list[object] = []
    pins: list[str | None] = []

    monkeypatch.setattr(
        runtime_settings, "get_agents", lambda name, default=None: settings.get(name, default)
    )

    async def list_models():
        return ["golden-model"]

    async def select(**_kwargs):
        return type(
            "Response",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Message",
                                (),
                                {"content": ('{"tools":["ws_read"],"preferred_tool":"ws_read"}')},
                            )()
                        },
                    )
                ],
                "usage": type("Usage", (), {"prompt_tokens": 9, "completion_tokens": 2})(),
            },
        )()

    async def stream(*, round_state=None, tool_choice=None, pin_provider=None, **_kwargs):
        nonlocal model_calls
        model_calls += 1
        choices.append(tool_choice)
        pins.append(pin_provider)
        round_state.update(
            {
                "provider": "golden-provider",
                "model": "golden-model",
                "prompt": 5,
                "completion": 1,
                "total": 6,
                "finish_reason": "stop",
            }
        )
        if model_calls == 1:
            yield "PRIVATE_UNGROUNDED_DRAFT"
        elif model_calls == 2:
            round_state.update(
                {
                    "finish_reason": "tool_calls",
                    "tool_calls": [
                        {
                            "id": "tool-1",
                            "name": "ws_read",
                            "arguments": '{"path":"readme.txt"}',
                        }
                    ],
                }
            )
        else:
            yield "grounded final"

    async def resolve_tools(_self, _model, _context=None):
        return ToolSet(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "ws_read",
                        "description": "Synthetic read.",
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                }
            ]
        )

    async def invoke(_tool, _context, _arguments):
        nonlocal tool_calls
        tool_calls += 1
        return "synthetic workspace result"

    monkeypatch.setattr(client_mod, "list_qualified_models", list_models)
    monkeypatch.setattr(client_mod, "create_chat_completion", select)
    monkeypatch.setattr(chat_run, "stream_chat_completion", stream)
    monkeypatch.setattr(tool_loop, "_invoke_tool", invoke)
    monkeypatch.setattr(base_mod.SimpleStreamingAgent, "_resolve_toolset", resolve_tools)

    context = UserContext(user_id="golden", request_time=datetime.now(UTC))
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
        events = [
            event
            async for event in GeneralAgent({"model": "golden-model"})._run_chat_streamed(
                _SENTINEL, context
            )
        ]
        receipts = execution.usage.receipts
        latch = execution.grounding

    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    expected = next(
        item for item in manifest["scenarios"] if item["id"] == "s25_grounding_repair_latch"
    )
    signatures = [_signature(event) for event in events]
    streamed = "".join(
        str(event.data or "") for event in events if event.type == EventType.STREAM_CHUNK
    )

    assert model_calls == expected["counts"]["model_calls"] == 3
    assert tool_calls == expected["counts"]["tool_calls"] == 1
    assert len(receipts) == expected["counts"]["receipts"] == 4
    assert latch.repair_count == expected["counts"]["repair_rounds"] == 1
    assert sum(receipt.prompt for receipt in receipts) == expected["budgets"]["prompt_tokens"]
    assert choices[0] == choices[1]
    assert choices[2] is None
    assert pins == [None, "golden-provider", "golden-provider"]
    assert streamed == "grounded final"
    assert "PRIVATE_UNGROUNDED_DRAFT" not in str(events)
    assert all("ws_read" not in str((event.metadata or {}).get("tool_intent")) for event in events)
    assert signatures[-2:] == ["status:tool_summary", "agent_complete"]
