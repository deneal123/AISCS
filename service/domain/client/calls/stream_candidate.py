"""Resolve one streaming provider candidate from run admission or compatibility state."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .. import active
from ..model_requirements import ModelRequirement
from ..protocol import ProviderFailure, ProviderFailureCode, ProviderProtocolError
from ..provider_operations import ProviderOperation
from .admitted_call import resolve_admitted_call

logger = logging.getLogger(__name__)


def _operation(requirement: ModelRequirement) -> ProviderOperation:
    if requirement.tools:
        return ProviderOperation.TOOL_CHAT
    if requirement.vision:
        return ProviderOperation.VISION_INPUT
    return ProviderOperation.CHAT


async def _qualified_model(
    provider: str,
    requested_model: str,
    requirement: ModelRequirement,
    qualify: Callable[..., Any],
) -> tuple[str | None, Exception | None]:
    decision = await qualify(
        provider,
        prefer=requested_model,
        requirement=requirement,
    )
    if decision.model:
        return decision.model, None
    logger.warning("Provider '%s' excluded before pinning: no_compatible_model", provider)
    return None, ProviderProtocolError(
        ProviderFailure(
            code=ProviderFailureCode.NO_COMPATIBLE_MODEL,
            retryable=False,
            provider=provider,
        )
    )


async def select_stream_candidate(
    provider: str,
    module: Any,
    *,
    admission: Any,
    requirement: ModelRequirement,
    requested_model: str,
    tools: list[dict] | None,
    tool_choice: str | dict | None,
    qualify: Callable[..., Any],
) -> tuple[Any | None, str | None, Any | None, Exception | None]:
    if admission is not None:
        admitted = resolve_admitted_call(
            admission,
            provider,
            operation=_operation(requirement),
            prefer=requested_model,
            tools=tools,
            tool_choice=tool_choice,
        )
        return (
            admitted.client,
            admitted.model,
            admitted.compiled_tools,
            admitted.failure,
        )
    client = (
        active.get_openai_client()
        if provider == active.ACTIVE_PROVIDER
        else getattr(module, "OPENAI_CLIENT", None)
        if module
        else None
    )
    if client is None:
        return None, None, None, None
    model, failure = await _qualified_model(
        provider,
        requested_model,
        requirement,
        qualify,
    )
    return client, model, None, failure


__all__ = ["select_stream_candidate"]
