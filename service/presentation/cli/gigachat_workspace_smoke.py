"""Opt-in grounded GigaChat smoke against a pre-provisioned isolated workspace.

The provisioning harness passes one JSON object on stdin with a private workspace
reference and a synthetic marker, then destroys that workspace in its own ``finally``
block. This process never prints either value. Unlike the older protocol probe, the
smoke does not set ``tool_choice`` itself: the production ToolSelectionController and
GroundingLatch own selection, one-repair enforcement, and final-answer acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from service.domain.capabilities.tool_spec import ToolSet
from service.domain.client import stream_chat_completion
from service.domain.client.registry import initialize_run_provider_admission
from service.domain.grounding import GroundingState
from service.domain.run_context import (
    GroundingRequirement,
    PrivateRunResources,
    use_run_execution,
)
from service.domain.runners.chat_stream_loop import ChatStreamLoopState, run_streamed_tool_loop
from service.domain.runners.support import _tools_to_openai
from service.domain.runners.tool_disclosure_state import ToolSelectionController
from service.domain.subagents.general import GeneralAgent
from service.domain.tools import unbilled_calls
from service.domain.tools.workspace_tools import ws_read, ws_write
from service.events import EventType
from service.presentation.cli.gigachat_smoke_support import (
    GigaChatSmokeFailure,
    bounded_failure_code,
    require_tool_model,
)
from service.schemas.agents import UserContext

_MODEL = os.getenv("GIGACHAT_SMOKE_MODEL", "GigaChat-2").strip() or "GigaChat-2"
_FILE = "s25-live.txt"


@dataclass(frozen=True, slots=True)
class _Input:
    workspace_ref: dict[str, Any]
    marker: str


@dataclass(frozen=True, slots=True)
class _RunResult:
    statuses: tuple[str, ...]
    tool_count: int
    charged_count: int
    tool_payloads: tuple[str, ...]


def _read_input() -> _Input:
    try:
        value = json.load(sys.stdin)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise GigaChatSmokeFailure("invalid_smoke_input") from None
    ref = value.get("workspace_ref") if isinstance(value, dict) else None
    marker = value.get("marker") if isinstance(value, dict) else None
    if not isinstance(ref, dict) or not isinstance(marker, str) or not marker:
        raise GigaChatSmokeFailure("invalid_smoke_input")
    required = ("workspace_id", "token", "user_id", "coordination_capability")
    if any(not str(ref.get(key) or "").strip() for key in required):
        raise GigaChatSmokeFailure("invalid_smoke_input")
    return _Input(dict(ref), marker[:512])


async def _gigachat_only_stream(**kwargs):
    """Disable failover for this proof without forcing a function choice."""

    kwargs["pin_provider"] = "gigachat"
    async for delta in stream_chat_completion(**kwargs):
        yield delta


def _tool_payloads(conversation: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        str(message.get("content") or "")
        for message in conversation
        if message.get("role") == "tool"
    )


def _validate_tool_attempts(statuses: tuple[str, ...]) -> None:
    """Accept the production latch's one bounded repair, but no retry loop."""

    if not 1 <= len(statuses) <= 2 or "succeeded" not in statuses:
        print(
            "workspace grounding attempt: "
            f"tool_events={len(statuses)} outcomes={','.join(sorted(set(statuses))) or 'none'}"
        )
        raise GigaChatSmokeFailure("tool_count_invalid")


async def _grounded_run(
    *,
    execution,
    context: UserContext,
    question: str,
) -> _RunResult:
    execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
    eligible = ToolSet(tools=_tools_to_openai([ws_read, ws_write]))
    controller = ToolSelectionController(
        eligible_toolset=eligible,
        question=question,
        agent_name="general",
        context=context,
        preferred_model=_MODEL,
        execution=execution,
    )
    disclosure = await controller.select(stage=1, remaining_prompt_tokens=24_000)
    if not execution.grounding.required:
        raise GigaChatSmokeFailure("grounding_not_activated")

    agent = GeneralAgent({"model": _MODEL})
    messages = [{"role": "user", "content": question}]
    state = ChatStreamLoopState(
        execution=execution,
        usage_scope=execution.usage.open_scope(),
        messages=messages,
        convo=list(messages),
        round_messages=list(messages),
        openai_tools=disclosure.toolset.tools,
        tool_index=controller.tool_index,
        tool_ctx=agent._build_tool_context(context),  # noqa: SLF001 - operational smoke
        disclosure_controller=controller,
        tool_summary={},
        model=_MODEL,
        max_tokens=256,
        max_continuations=0,
        max_tool_rounds=2,
        prompt_budget=24_000,
        estimated_prompt_spent=disclosure.estimated_prompt_tokens,
        context=context,
        tool_choice=disclosure.tool_choice,
        tool_dedup_mode="enforce",
    )
    events = [
        event
        async for event in run_streamed_tool_loop(
            state,
            agent_name="general",
            execute_tool_round=agent._execute_tool_round,  # noqa: SLF001
            estimate_prompt_tokens=lambda _messages, _tools: 1,
            stream=_gigachat_only_stream,
        )
    ]
    if execution.grounding.state is not GroundingState.SATISFIED:
        raise GigaChatSmokeFailure("grounding_not_satisfied")
    progress = [
        (event.metadata or {}).get("tool_progress")
        for event in events
        if event.type == EventType.TOOL_CALL_COMPLETE
    ]
    statuses = tuple(
        str(item.get("status") or "unknown") for item in progress if isinstance(item, dict)
    )
    _validate_tool_attempts(statuses)
    charged = sum(
        bool((event.metadata or {}).get("billable_tools"))
        for event in events
        if event.type == EventType.TOOL_CALL_COMPLETE
    )
    return _RunResult(statuses, len(statuses), charged, _tool_payloads(state.convo))


def _read_content(payloads: tuple[str, ...]) -> str:
    for payload in reversed(payloads):
        try:
            value = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("content"), str):
            return value["content"]
    return ""


async def _isolated_run(
    smoke: _Input,
    context: UserContext,
    question: str,
) -> tuple[_RunResult, dict[str, int]]:
    resources = PrivateRunResources.from_request(workspace_ref=smoke.workspace_ref)
    with use_run_execution(resources) as execution, unbilled_calls.collect():
        await initialize_run_provider_admission(execution)
        result = await _grounded_run(
            execution=execution,
            context=context,
            question=question,
        )
        if execution.provider_session.pinned_provider != "gigachat":
            raise GigaChatSmokeFailure("provider_not_pinned")
        if smoke.marker in repr(execution.provider_session.rounds):
            raise GigaChatSmokeFailure("private_metadata_leak")
        return result, execution.usage.bounded_summary()


async def run_workspace_certification(*, qualify: bool = True) -> None:
    if qualify:
        await require_tool_model(_MODEL)
    smoke = _read_input()
    context = UserContext(
        user_id=str(smoke.workspace_ref["user_id"]),
        request_time=datetime.now(UTC),
        thread_id=str(smoke.workspace_ref.get("thread_id") or "s25-live"),
        workspace_ref=smoke.workspace_ref,
    )
    written, written_usage = await _isolated_run(
        smoke,
        context,
        (
            f"Write a file named {_FILE}. Its entire content must be exactly the value "
            "between the tags below, without the tags, a label, quotes, spaces, or a newline: "
            f"<value>{smoke.marker}</value>"
        ),
    )
    read, read_usage = await _isolated_run(
        smoke,
        context,
        f"Read {_FILE} from the workspace before answering.",
    )
    observed = _read_content(read.tool_payloads)
    if observed != smoke.marker:
        print(
            "workspace content verification: status=mismatch "
            f"expected_chars={len(smoke.marker)} observed_chars={len(observed)}"
        )
        raise GigaChatSmokeFailure("workspace_content_mismatch")
    if written.charged_count != 1 or read.charged_count != 1:
        raise GigaChatSmokeFailure("workspace_billing_invalid")

    statuses = sorted({*written.statuses, *read.statuses})
    model_calls = written_usage["call_count"] + read_usage["call_count"]
    prompt = written_usage["prompt_tokens"] + read_usage["prompt_tokens"]
    completion = written_usage["completion_tokens"] + read_usage["completion_tokens"]
    print(
        "workspace grounding: provider=gigachat "
        f"model={_MODEL} tools={written.tool_count + read.tool_count} "
        f"charged_tools={written.charged_count + read.charged_count} "
        f"outcomes={','.join(statuses)} model_calls={model_calls} "
        f"prompt={prompt} completion={completion}"
    )


async def _main() -> None:
    await run_workspace_certification()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as exc:  # noqa: BLE001 - operational output must remain bounded
        print(f"gigachat workspace smoke: FAILED code={bounded_failure_code(exc)}")
        raise SystemExit(1) from None
    print("gigachat workspace smoke: OK")
