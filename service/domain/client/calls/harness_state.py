"""Приватное состояние привязано к сохранённому ответу, а не старому checkpoint."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from service.domain.client.protocol import ProviderRunSession
from service.shared.harness_protocol import HarnessFailure, ProviderBinding


def capture_state(
    session: ProviderRunSession | None, *, provider: str, model: str
) -> ProviderBinding:
    return ProviderBinding(
        provider=provider,
        model=model,
        state_id=session.private_state(provider) if session is not None else None,
    )


def restore_state(
    session: ProviderRunSession | None,
    receipt: Mapping[str, Any],
    *,
    provider: str,
    model: str,
) -> None:
    raw = receipt.get("provider_state")
    if raw is None:
        if provider == "gigachat" and (receipt.get("message") or {}).get("tool_calls"):
            raise HarnessFailure("provider_state_incompatible")
        return
    try:
        binding = ProviderBinding.model_validate(raw)
    except ValidationError:
        raise HarnessFailure("provider_state_incompatible") from None
    if binding.provider != provider or binding.model != model:
        raise HarnessFailure("provider_state_incompatible")
    if session is None:
        if binding.state_id is not None:
            raise HarnessFailure("provider_state_incompatible")
        return
    session.clear_private_state(provider)
    if binding.state_id is not None:
        session.set_private_state(provider, binding.state_id)
