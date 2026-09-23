"""Stable runtime projections precomputed by the capability compiler."""

from __future__ import annotations


def _catalog():
    from .registry import _catalog as registry_catalog

    return registry_catalog()


def route_vocabulary() -> set[str]:
    return set(_catalog().projections.route_vocabulary)


def forced_allowlist() -> set[str]:
    return set(_catalog().projections.forced_allowlist)


def valid_router_tools() -> set[str]:
    return set(_catalog().projections.valid_router_tools)


def decomposable_names() -> list[str]:
    return list(_catalog().projections.decomposable_names)


def route_labels() -> dict[str, str]:
    return dict(_catalog().projections.route_labels)


def billing_names() -> set[str]:
    # Historical helper means route billing names, while the full catalog projection
    # also includes native/dynamic tool surcharge contracts.
    return {spec.billing_name for spec in _catalog().agents.values() if spec.billing_name}


def confirm_default_names() -> set[str]:
    return set(_catalog().projections.confirm_default_names)


def required_input_type(name: str) -> str | None:
    return _catalog().projections.required_input_types.get(str(name or "").strip().lower())


def modality_conflict(name: str, input_type: str | None) -> bool:
    required = required_input_type(name)
    return bool(required) and input_type != required


def forced_by_input_type(input_type: str | None, *, beats_toggles: bool) -> str | None:
    if not input_type:
        return None
    projection = (
        _catalog().projections.forced_before_toggles
        if beats_toggles
        else _catalog().projections.forced_after_toggles
    )
    return projection.get(input_type)


def render_auto_routes() -> str:
    return _catalog().projections.auto_routes


def render_auto_route_enum() -> str:
    return _catalog().projections.auto_route_enum


def render_decompose_categories() -> str:
    return _catalog().projections.decompose_categories


__all__ = [
    "billing_names",
    "confirm_default_names",
    "decomposable_names",
    "forced_allowlist",
    "forced_by_input_type",
    "modality_conflict",
    "render_auto_route_enum",
    "render_auto_routes",
    "render_decompose_categories",
    "required_input_type",
    "route_labels",
    "route_vocabulary",
    "valid_router_tools",
]
