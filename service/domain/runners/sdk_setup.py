"""Construction helpers for the optional Agents SDK execution path."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_sdk_agent(
    owner: Any,
    context: Any,
    *,
    agent_cls: Any,
    model_settings_cls: Any,
    model_factory: Callable[[str], Any],
) -> Any:
    """Build an SDK Agent while keeping the model id out of ModelSettings."""
    model_id = None
    if isinstance(owner.model_settings, dict):
        raw_settings = dict(owner.model_settings)
        model_id = raw_settings.pop("model", None)
        settings = model_settings_cls(**raw_settings)
    else:
        settings = owner.model_settings
    if owner._is_blocked_chat_model(model_id):
        model_id = None

    agent_kwargs: dict[str, Any] = {
        "name": owner.name,
        "instructions": owner._compose_system_instructions(context),
        "tools": owner.tools,
        "input_guardrails": owner.input_guardrails,
        "output_guardrails": owner.output_guardrails,
        "model_settings": settings,
    }
    if model_id:
        agent_kwargs["model"] = model_factory(model_id)
    return agent_cls(**agent_kwargs)


def wrap_sdk_context(context: Any, *, wrapper_cls: Any) -> Any:
    """Keep SDK context serialization fail-soft for old context schemas."""
    from service.domain.run_context import tool_context_payload

    payload = tool_context_payload(context)
    return wrapper_cls(payload)
