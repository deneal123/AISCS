"""Progressive disclosure of already-authorized tools.

The selector is intentionally *after* ``resolve_toolset``: it never changes policy,
credentials, confirmation gates, or model capability checks. It only reduces schemas
sent to the primary model when a run has a large (usually MCP) candidate set.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from service.domain.llm_response import first_message_content
from service.domain.model_runtime import invoke_model_call
from service.domain.run_context import (
    GroundingReason,
    RunExecutionContext,
    require_execution,
)
from service.domain.usage_ledger import UsageKind
from service.events import AgentEvent, EventType
from service.shared import deadline

from .tool_disclosure_usage import usage_event as usage_event
from .tool_registry import get_tool_spec
from .tool_spec import NOT_IN_TIER, Omission, ToolSet

logger = logging.getLogger(__name__)

_MAX_HINT_CHARS = 240
_MAX_INPUT_CHARS = 4_000
_SELECTOR_MAX_TOKENS = 180

_SYSTEM = """Ты выбираешь, какие ИНСТРУМЕНТЫ показать основной модели.
Тебе даны только уже разрешённые инструменты; нельзя добавлять имена, которых нет в manifest.
Выбери минимальный достаточный набор для выполнения запроса. Инструмент может понадобиться
на следующем шаге, если это явно следует из задачи (например, чтение и правка файла).
Никогда не выполняй задачу и не выдавай аргументы вызова. Ответь строго JSON-объектом вида
{\"tools\":[\"tool_name\"],\"preferred_tool\":\"tool_name\"}; preferred_tool может быть
null и обязан входить в tools. Пустой список допустим, если инструменты не нужны."""


class _RequiredSelectionEmpty(ValueError):
    """Internal control signal; never serialized or logged by class name."""


@dataclass(frozen=True, slots=True)
class DisclosureResult:
    toolset: ToolSet
    event: AgentEvent | None = None
    usage: dict[str, Any] | None = None
    estimated_prompt_tokens: int = 0
    preferred_tool: str | None = None
    grounding_required: bool = False
    intent_event: AgentEvent | None = None


def _name(tool: Any) -> str:
    if isinstance(tool, dict):
        return str((tool.get("function") or {}).get("name") or "")
    return str(getattr(tool, "name", "") or "")


def _compact(text: Any) -> str:
    return " ".join(str(text or "").split())[:_MAX_HINT_CHARS]


def build_manifest(tools: list[Any]) -> list[dict[str, str]]:
    """Build the selector input without JSON schemas or user-controlled tool arguments."""
    manifest: list[dict[str, str]] = []
    for tool in tools:
        name = _name(tool)
        if not name:
            continue
        spec = get_tool_spec(name)
        description = (
            (tool.get("function") or {}).get("description", "")
            if isinstance(tool, dict)
            else getattr(tool, "description", "")
        )
        manifest.append(
            {
                "name": name,
                "source": str(getattr(spec, "source", "native") or "native"),
                "hint": _compact(getattr(spec, "selector_hint", "") or description or name),
            }
        )
    return manifest


def _settings(context: Any | None) -> tuple[str, int, float, set[str]]:
    from service.settings import config
    from service.shared.agent_settings import runtime_settings

    mode = (
        str(
            runtime_settings.get_agents("tool_disclosure_mode", config.agents.tool_disclosure_mode)
            or "off"
        )
        .strip()
        .lower()
    )
    if mode not in {"off", "observe", "enforce"}:
        mode = "off"
    raw_minimum = runtime_settings.get_agents(
        "tool_disclosure_min_candidate_count", config.agents.tool_disclosure_min_candidate_count
    )
    raw_timeout = runtime_settings.get_agents(
        "tool_disclosure_timeout_sec", config.agents.tool_disclosure_timeout_sec
    )
    raw_canary = runtime_settings.get_agents(
        "tool_disclosure_canary_user_ids", config.agents.tool_disclosure_canary_user_ids
    )
    try:
        minimum = max(1, int(raw_minimum))
    except (TypeError, ValueError):
        minimum = 15
    try:
        timeout = max(1.0, float(raw_timeout))
    except (TypeError, ValueError):
        timeout = 8.0
    canary = {part.strip() for part in str(raw_canary or "").split(",") if part.strip()}
    return mode, minimum, timeout, canary


def _can_use(
    mode: str,
    minimum: int,
    canary: set[str],
    context: Any | None,
    count: int,
    *,
    grounding_required: bool,
) -> bool:
    if grounding_required:
        return count > 0
    if not grounding_required and (mode == "off" or count < minimum):
        return False
    user_id = str(getattr(context, "user_id", "") or "")
    return not canary or user_id in canary


def _selector_payload(
    *,
    question: str,
    agent_name: str,
    context: Any | None,
    manifest: list[dict[str, str]],
    executed: list[dict[str, str]],
) -> str:
    from service.domain.run_context import policy_flag

    signals = {
        "agent": agent_name,
        "workspace_available": policy_flag(context, "workspace_tools_enabled"),
        "tables_available": bool(getattr(context, "tabular_files", None)),
        "repo_graph_available": bool(getattr(context, "repo_graph_ids", None)),
        "fresh_data_allowed": policy_flag(context, "web_tool_enabled"),
        "executed_tools": executed,
    }
    payload = {
        "request": str(question or "")[:_MAX_INPUT_CHARS],
        "signals": signals,
        "manifest": manifest,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _estimated_selector_prompt(payload: str) -> int:
    """Conservative prompt estimate used by the run-wide prompt budget."""
    from service.shared.token_budget import estimate_tokens

    return estimate_tokens(_SYSTEM) + estimate_tokens(payload)


def _parse_selection(content: str, allowed: set[str]) -> tuple[list[str], str | None]:
    raw = json.loads(content)
    if (
        not isinstance(raw, dict)
        or set(raw) not in ({"tools"}, {"tools", "preferred_tool"})
        or not isinstance(raw["tools"], list)
    ):
        raise ValueError("selector response is not an exact tools object")
    names = raw["tools"]
    if not all(isinstance(name, str) and name for name in names):
        raise ValueError("selector response contains a non-string tool name")
    if len(names) != len(set(names)) or any(name not in allowed for name in names):
        raise ValueError("selector response contains duplicate or unavailable tools")
    preferred = raw.get("preferred_tool")
    if preferred is not None and (not isinstance(preferred, str) or preferred not in names):
        raise ValueError("preferred tool is unavailable")
    return names, preferred


def _event(
    *,
    agent_name: str,
    mode: str,
    stage: int,
    candidates: int,
    selected: int,
    offered: int,
    fallback_reason: str = "",
    schema_tokens_saved: int = 0,
) -> AgentEvent:
    payload: dict[str, Any] = {
        "mode": mode,
        "stage": stage,
        "candidates": candidates,
        "selected": selected,
        "offered": offered,
        "enforced": mode == "enforce" and not fallback_reason,
        "schema_tokens_saved": max(0, int(schema_tokens_saved)),
    }
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={"kind": "tool_disclosure", "tool_disclosure": payload},
    )


def _intent_event(
    *,
    agent_name: str,
    reason: str,
    required: bool,
    forced: bool,
    candidates: int,
    offered: int,
    fallback_reason: str = "",
) -> AgentEvent:
    payload: dict[str, Any] = {
        "required": bool(required),
        "forced": bool(forced),
        "candidates": max(0, int(candidates)),
        "offered": max(0, int(offered)),
        "reason": reason,
    }
    if fallback_reason:
        payload["fallback_reason"] = fallback_reason
    return AgentEvent(
        type=EventType.STATUS_UPDATE,
        agent_name=agent_name,
        data="",
        metadata={"kind": "tool_intent", "tool_intent": payload},
    )


def _schema_tokens(tools: list[Any]) -> int:
    from service.shared.token_budget import estimate_tokens

    return estimate_tokens(json.dumps(tools, ensure_ascii=False, default=str))


@dataclass(slots=True)
class _DisclosureState:
    toolset: ToolSet
    candidates: list[Any]
    mode: str
    agent_name: str
    stage: int
    grounding_reason: str
    grounding_required: bool
    estimated_prompt_tokens: int
    candidate_schema_tokens: int
    usage: dict[str, Any]

    def intent(self, *, forced: bool, offered: int, fallback_reason: str = "") -> AgentEvent | None:
        if not self.grounding_required:
            return None
        return _intent_event(
            agent_name=self.agent_name,
            reason=self.grounding_reason,
            required=True,
            forced=forced,
            candidates=len(self.candidates),
            offered=offered,
            fallback_reason=fallback_reason,
        )


def _fallback_result(state: _DisclosureState, reason: str) -> DisclosureResult:
    logger.info("progressive tool selector fell back code=%s", reason)
    count = len(state.candidates)
    return DisclosureResult(
        toolset=state.toolset,
        event=_event(
            agent_name=state.agent_name,
            mode=state.mode,
            stage=state.stage,
            candidates=count,
            selected=count,
            offered=count,
            fallback_reason=reason,
            schema_tokens_saved=0,
        ),
        usage=state.usage or None,
        estimated_prompt_tokens=state.estimated_prompt_tokens,
        grounding_required=state.grounding_required,
        intent_event=state.intent(forced=False, offered=count, fallback_reason=reason),
    )


def _selected_result(
    state: _DisclosureState,
    selected_names: list[str],
    preferred_tool: str | None,
) -> DisclosureResult:
    selected_set = set(selected_names)
    selected = [tool for tool in state.candidates if _name(tool) in selected_set]
    enforce = state.mode == "enforce"
    offered = len(selected) if enforce else len(state.candidates)
    result_toolset = state.toolset
    if enforce:
        omitted = [
            Omission(_name(tool), NOT_IN_TIER, "progressive_disclosure")
            for tool in state.candidates
            if _name(tool) not in selected_set
        ]
        result_toolset = ToolSet(
            tools=selected,
            omissions=[*state.toolset.omissions, *omitted],
        )
    return DisclosureResult(
        toolset=result_toolset,
        event=_event(
            agent_name=state.agent_name,
            mode=state.mode,
            stage=state.stage,
            candidates=len(state.candidates),
            selected=len(selected),
            offered=offered,
            schema_tokens_saved=state.candidate_schema_tokens - _schema_tokens(selected),
        ),
        usage=state.usage,
        estimated_prompt_tokens=state.estimated_prompt_tokens,
        preferred_tool=preferred_tool,
        grounding_required=state.grounding_required,
        intent_event=state.intent(forced=True, offered=offered),
    )


async def _run_selector(
    *,
    payload: str,
    allowed: set[str],
    preferred_model: str,
    timeout: float,
    grounding_required: bool,
    execution: RunExecutionContext,
) -> tuple[list[str], str | None, str | None]:
    try:
        if deadline.must_finalize():
            raise TimeoutError
        from service.domain.client import create_chat_completion, list_qualified_models
        from service.domain.subagents.utils import pick_meta_model

        model = pick_meta_model(await list_qualified_models(), preferred_model)
        if not model:
            raise RuntimeError
        result = await asyncio.wait_for(
            invoke_model_call(
                create_chat_completion,
                kind=UsageKind.TOOL_SELECTOR,
                execution=execution,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": payload},
                ],
                model=model,
                temperature=0.0,
                max_tokens=_SELECTOR_MAX_TOKENS,
            ),
            timeout=deadline.clamp(timeout),
        )
        response = result.response
        selected, preferred = _parse_selection(first_message_content(response).strip(), allowed)
        if grounding_required and not selected:
            raise _RequiredSelectionEmpty
        if grounding_required and not preferred:
            raise ValueError
        return selected, preferred, None
    except TimeoutError:
        return [], None, "deadline"
    except _RequiredSelectionEmpty:
        return [], None, "empty_selection"
    except (json.JSONDecodeError, ValueError):
        return [], None, "invalid_selection"
    except Exception:
        return [], None, "unavailable"


async def disclose(
    toolset: ToolSet,
    *,
    question: str,
    agent_name: str,
    context: Any | None,
    preferred_model: str,
    stage: int,
    executed: list[dict[str, str]],
    remaining_prompt_tokens: int | None = None,
    execution: RunExecutionContext | None = None,
) -> DisclosureResult:
    """Select a tier or return the exact original ToolSet on every degradation path."""
    execution = require_execution(execution)
    candidates = list(toolset.tools)
    mode, minimum, timeout, canary = _settings(context)
    grounding_reason = execution.policy.grounding_reason
    grounding_required = grounding_reason is not GroundingReason.NONE
    if execution.grounding.state.value == "satisfied":
        grounding_required = False
    if grounding_required and not candidates:
        return DisclosureResult(
            toolset,
            grounding_required=True,
            intent_event=_intent_event(
                agent_name=agent_name,
                reason=grounding_reason.value,
                required=True,
                forced=False,
                candidates=0,
                offered=0,
                fallback_reason="no_eligible_tools",
            ),
        )
    if not _can_use(
        mode,
        minimum,
        canary,
        context,
        len(candidates),
        grounding_required=grounding_required,
    ):
        return DisclosureResult(toolset)

    manifest = build_manifest(candidates)
    allowed = {item["name"] for item in manifest}
    payload = _selector_payload(
        question=question,
        agent_name=agent_name,
        context=context,
        manifest=manifest,
        executed=executed,
    )
    estimated_prompt_tokens = _estimated_selector_prompt(payload)
    candidate_schema_tokens = _schema_tokens(candidates)
    usage_cursor = execution.usage.cursor()
    state = _DisclosureState(
        toolset=toolset,
        candidates=candidates,
        mode=mode,
        agent_name=agent_name,
        stage=stage,
        grounding_reason=grounding_reason.value,
        grounding_required=grounding_required,
        estimated_prompt_tokens=estimated_prompt_tokens,
        candidate_schema_tokens=candidate_schema_tokens,
        usage={},
    )
    if remaining_prompt_tokens is not None and estimated_prompt_tokens > remaining_prompt_tokens:
        return _fallback_result(state, "prompt_budget")
    selected_names, preferred_tool, fallback_reason = await _run_selector(
        payload=payload,
        allowed=allowed,
        preferred_model=preferred_model,
        timeout=timeout,
        grounding_required=grounding_required,
        execution=execution,
    )
    state.usage = execution.usage.project_kind_since(
        usage_cursor,
        UsageKind.TOOL_SELECTOR,
    )
    if fallback_reason is not None:
        return _fallback_result(state, fallback_reason)
    return _selected_result(state, selected_names, preferred_tool)
