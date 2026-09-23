"""Isolated bridge for legacy direct callers without a run provider snapshot.

Production agents entrypoints initialize :class:`RunProviderAdmission`.  A small
number of direct unit/internal callers still exercise lower-level helpers; mutable
provider globals are confined here until those callers are removed.
"""

from __future__ import annotations

from typing import Any


def active_provider_name() -> str:
    from . import get_active_provider

    return get_active_provider()


def active_provider_client() -> Any:
    from . import get_openai_client

    return get_openai_client()


async def resolve_model_client(
    model: str,
    *,
    preferred_provider: str | None = None,
) -> tuple[str | None, Any]:
    from . import (
        get_active_provider,
        get_model_catalog,
        get_openai_client,
        get_provider_module,
    )

    _, owners = await get_model_catalog()
    active = get_active_provider()
    provider = preferred_provider or owners.get(model) or active
    module = get_provider_module(provider)
    client = getattr(module, "OPENAI_CLIENT", None) if module is not None else None
    if client is None and provider == active:
        client = get_openai_client()
    return provider, client


async def list_inventory_models() -> list[str]:
    from . import list_available_models

    return await list_available_models()


async def provider_order() -> list[str]:
    from . import build_provider_order, get_active_provider, provider_policy

    return await provider_policy.drop_hard_off(build_provider_order(get_active_provider()))


async def provider_client_models(provider: str) -> tuple[Any, list[str]]:
    from . import get_provider_module

    module = get_provider_module(provider)
    client = getattr(module, "OPENAI_CLIENT", None) if module is not None else None
    if module is None:
        return client, []
    try:
        models = list(await module.list_available_models() or [])
    except Exception:  # noqa: BLE001 - compatibility boundary stays fail-open
        models = []
    return client, models


__all__ = [
    "active_provider_client",
    "active_provider_name",
    "list_inventory_models",
    "provider_client_models",
    "provider_order",
    "resolve_model_client",
]
