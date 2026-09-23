"""Provider-neutral model capability qualification.

The registry owns provider discovery and ordering.  This module owns only the
deterministic decision over one immutable inventory snapshot, keeping that policy
small enough to test without importing provider clients.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from .model_catalog import ModelCatalogSource, ProviderModelCatalog
from .model_requirements import (
    ModelQualification,
    ModelRequirement,
    ProviderQualificationStatus,
)
from .providers.spec import ProviderSpec

ModelPicker = Callable[[list[str], str | None], str | None]


def fallback_model_allowed(
    spec: ProviderSpec | None,
    model: str,
    requirement: ModelRequirement,
) -> bool:
    """Check a cold-start model against an exact declared capability profile."""
    capabilities = spec.fallback_capabilities(model) if spec is not None else frozenset()
    return (
        (not requirement.chat or "chat" in capabilities)
        and (not requirement.tools or "tools" in capabilities)
        and (not requirement.vision or "vision" in capabilities)
    )


async def qualify_inventory_models(
    *,
    spec: ProviderSpec | None,
    models: list[str],
    requirement: ModelRequirement,
    is_chat_capable: Callable[[str], bool],
) -> list[str]:
    """Keep only live/stale models whose required capabilities are known."""
    require_declared = bool(spec is not None and spec.require_declared_model_capabilities)

    def _declared(model: str, capability: str) -> bool:
        return bool(spec is not None and capability in spec.capabilities_for_model(model))

    candidates = [
        model
        for model in models
        if not requirement.chat
        or (_declared(model, "chat") if require_declared else is_chat_capable(model))
    ]
    if requirement.tools:
        if require_declared:
            candidates = [model for model in candidates if _declared(model, "tools")]
        else:
            from service.shared.model_catalog import model_supports_tools

            supported = await asyncio.gather(*(model_supports_tools(model) for model in candidates))
            candidates = [
                model for model, allowed in zip(candidates, supported, strict=True) if allowed
            ]
    if requirement.vision:
        if require_declared:
            candidates = [model for model in candidates if _declared(model, "vision")]
        else:
            from service.shared.model_catalog import get_openrouter_catalog, model_has_capability

            catalog = await get_openrouter_catalog()
            candidates = [
                model for model in candidates if model_has_capability(model, "vision", catalog)
            ]
    return candidates


async def qualify_catalog(
    *,
    provider: str,
    spec: ProviderSpec | None,
    catalog: ProviderModelCatalog,
    requirement: ModelRequirement,
    prefer: str | None,
    is_chat_capable: Callable[[str], bool],
    pick_model: ModelPicker,
) -> ModelQualification:
    """Produce the bounded qualification decision for one catalog snapshot."""
    if catalog.source is ModelCatalogSource.STATIC_FALLBACK:
        candidates = [
            model for model in catalog.models if fallback_model_allowed(spec, model, requirement)
        ]
    else:
        candidates = await qualify_inventory_models(
            spec=spec,
            models=list(catalog.models),
            requirement=requirement,
            is_chat_capable=is_chat_capable,
        )

    selected = prefer if prefer and prefer in candidates else pick_model(candidates, prefer)
    if selected is not None:
        status = (
            ProviderQualificationStatus.COMPATIBLE_UNVERIFIED
            if catalog.source is ModelCatalogSource.STATIC_FALLBACK
            else ProviderQualificationStatus.COMPATIBLE
        )
    elif not catalog.discovery_available:
        status = ProviderQualificationStatus.CATALOG_UNAVAILABLE
    else:
        status = ProviderQualificationStatus.NO_COMPATIBLE_MODEL
    return ModelQualification(
        provider=provider,
        requirement=requirement,
        status=status,
        catalog_source=catalog.source,
        catalog_status=catalog.status,
        candidate_count=len(candidates),
        model=selected,
    )


__all__ = ["fallback_model_allowed", "qualify_catalog", "qualify_inventory_models"]
