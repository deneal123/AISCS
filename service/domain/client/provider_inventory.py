"""Aggregate model inventory projections outside the provider registry."""

from __future__ import annotations

from .model_catalog import ModelCatalogSource
from .model_qualification import fallback_model_allowed, qualify_inventory_models
from .model_requirements import ModelRequirement


async def build_model_catalog(active: str) -> tuple[list[str], dict[str, str]]:
    from .registry import _fetch_grouped_models, _parse_fallback_order

    normalized = (active or "").strip().lower()
    grouped = await _fetch_grouped_models()
    priority = [normalized] + [name for name in _parse_fallback_order() if name != normalized]
    ordered = [name for name in priority if name in grouped]
    ordered.extend(name for name in grouped if name not in priority)
    aggregated: list[str] = []
    owners: dict[str, str] = {}
    seen: set[str] = set()
    for name in ordered:
        for model in grouped.get(name, ()):
            owners.setdefault(model, name)
            if model not in seen:
                seen.add(model)
                aggregated.append(model)
    return aggregated, owners


async def build_qualified_model_catalog(
    active: str,
    *,
    requirement: ModelRequirement | None = None,
) -> tuple[list[str], dict[str, str]]:
    from service.domain.run_context import current_execution

    from .registry import (
        _fetch_provider_catalogs,
        _parse_fallback_order,
        _pick_chat_capable_model,
        get_spec,
        is_chat_capable,
    )

    effective = requirement or ModelRequirement()
    execution = current_execution()
    if execution is not None and execution.provider_admission is not None:
        return execution.provider_admission.qualified_catalog(
            effective,
            pick_model=_pick_chat_capable_model,
        )

    normalized = (active or "").strip().lower()
    catalogs = await _fetch_provider_catalogs()
    priority = [normalized] + [name for name in _parse_fallback_order() if name != normalized]
    ordered = [name for name in priority if name in catalogs]
    ordered.extend(name for name in catalogs if name not in priority)
    qualified: list[str] = []
    owners: dict[str, str] = {}
    seen: set[str] = set()
    for name in ordered:
        catalog = catalogs[name]
        spec = get_spec(name)
        if catalog.source is ModelCatalogSource.STATIC_FALLBACK:
            candidates = [
                model for model in catalog.models if fallback_model_allowed(spec, model, effective)
            ]
        else:
            candidates = await qualify_inventory_models(
                spec=spec,
                models=list(catalog.models),
                requirement=effective,
                is_chat_capable=is_chat_capable,
            )
        for model in candidates:
            owners.setdefault(model, name)
            if model not in seen:
                seen.add(model)
                qualified.append(model)
    return qualified, owners


__all__ = ["build_model_catalog", "build_qualified_model_catalog"]
