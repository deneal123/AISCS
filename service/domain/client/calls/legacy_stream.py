"""Isolated string-stream compatibility facade.

Production orchestration calls :func:`stream_provider_completion` with a typed
``ProviderRoundState``. Only historical direct callers may request the former mutable
usage projection through this module.
"""

from __future__ import annotations

from contextlib import nullcontext

from service.domain.client.protocol import ProviderRoundState

from .streaming import stream_provider_completion


async def stream_chat_completion(messages: list[dict], model: str, **kwargs):
    from service.domain.legacy_usage import extract_legacy_projection
    from service.domain.run_context import (
        PrivateRunResources,
        current_execution,
        use_run_execution,
    )

    projection = extract_legacy_projection(kwargs)
    current = current_execution()
    scope = (
        nullcontext(current) if current is not None else use_run_execution(PrivateRunResources())
    )
    with scope as execution:
        state = kwargs.pop("round_state", None) or ProviderRoundState()
        kwargs.setdefault("provider_session", execution.provider_session)
        async for delta in stream_provider_completion(
            messages,
            model,
            round_state=state,
            **kwargs,
        ):
            yield delta
    if projection is not None:
        projection.update(state.compatibility_payload())


__all__ = ["stream_chat_completion"]
