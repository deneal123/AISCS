"""Process-wide static catalog and run-local capability admission."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from threading import Lock

from service.settings import config
from service.shared.agent_settings import runtime_settings

from .catalog import (
    CapabilityPolicyView,
    RunCapabilitySnapshot,
    StaticCapabilityCatalog,
    frozen_mapping,
)
from .compiler import compile_static_catalog
from .metrics import record
from .tool_spec import GROUNDING_ROLES, TOOL_EFFECTS, ToolSpec

_ACTIVE: StaticCapabilityCatalog | None = None
_LOCK = Lock()
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class McpAdmission:
    accepted: tuple[ToolSpec, ...]
    rejected: int
    reasons: dict[str, int]


def initialize_static_catalog() -> StaticCapabilityCatalog:
    """Compile once per process; static defects are intentionally not caught."""

    global _ACTIVE
    if _ACTIVE is not None:
        return _ACTIVE
    with _LOCK:
        if _ACTIVE is None:
            _ACTIVE = compile_static_catalog()
            record("startup", "ok")
    return _ACTIVE


def get_static_catalog() -> StaticCapabilityCatalog:
    return initialize_static_catalog()


def _policy_view(catalog: StaticCapabilityCatalog) -> CapabilityPolicyView:
    fields = {
        spec.enabled_field
        for spec in (
            *catalog.agents.values(),
            *catalog.workflows.values(),
            *catalog.native_tools.values(),
        )
        if spec.enabled_field
    }
    enabled = {
        field: bool(runtime_settings.get_agents(field, getattr(config.agents, field)))
        for field in sorted(fields)
    }
    return CapabilityPolicyView(enabled=frozen_mapping(enabled))


def _valid_dynamic_spec(spec: object) -> bool:
    if not isinstance(spec, ToolSpec) or spec.source != "mcp":
        return False
    name = str(spec.name or "").strip()
    return bool(
        _NAME.fullmatch(name)
        and str(getattr(spec.tool, "name", "") or "") == name
        and spec.effect in TOOL_EFFECTS
        and not (set(spec.grounding_roles) - GROUNDING_ROLES)
        and spec.billing_name == "mcp_tool"
    )


def admit_mcp_specs(
    specs: Iterable[ToolSpec], catalog: StaticCapabilityCatalog | None = None
) -> McpAdmission:
    """Admit a disjoint immutable MCP overlay without exposing rejected names."""

    static = catalog or get_static_catalog()
    accepted: list[ToolSpec] = []
    names: set[str] = set()
    reasons: dict[str, int] = {}
    for spec in specs:
        reason = ""
        if not _valid_dynamic_spec(spec):
            reason = "invalid_spec"
        elif spec.name in static.native_tools:
            reason = "native_collision"
        elif spec.name in names:
            reason = "duplicate_name"
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
            record("mcp_admission", "rejected", reason)
            continue
        accepted.append(spec)
        names.add(spec.name)
    if accepted:
        record("mcp_admission", "ok")
    return McpAdmission(tuple(accepted), sum(reasons.values()), reasons)


def build_run_capability_snapshot(
    mcp_specs: Iterable[ToolSpec] = (),
) -> RunCapabilitySnapshot:
    static = get_static_catalog()
    admission = admit_mcp_specs(mcp_specs, static)
    return RunCapabilitySnapshot(
        static=static,
        mcp_overlay=frozen_mapping({spec.name: spec for spec in admission.accepted}),
        policy=_policy_view(static),
    )


def reset_static_catalog_for_tests() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None


__all__ = [
    "McpAdmission",
    "admit_mcp_specs",
    "build_run_capability_snapshot",
    "get_static_catalog",
    "initialize_static_catalog",
]
