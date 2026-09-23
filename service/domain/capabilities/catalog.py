"""Immutable compiled capability contracts used by every run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .agent_spec import AgentSpec
from .tool_spec import Omission, ToolSpec
from .workflow_spec import WorkflowSpec


def frozen_mapping(values: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    """Copy before freezing so a caller cannot mutate the backing dictionary."""

    return MappingProxyType(dict(values or {}))


@dataclass(frozen=True, slots=True)
class CapabilityProjections:
    route_vocabulary: frozenset[str]
    forced_allowlist: frozenset[str]
    valid_router_tools: frozenset[str]
    decomposable_names: tuple[str, ...]
    route_labels: Mapping[str, str]
    billing_names: frozenset[str]
    tool_billing_names: Mapping[str, str]
    confirm_default_names: frozenset[str]
    required_input_types: Mapping[str, str]
    forced_before_toggles: Mapping[str, str]
    forced_after_toggles: Mapping[str, str]
    auto_routes: str
    auto_route_enum: str
    decompose_categories: str


@dataclass(frozen=True, slots=True)
class StaticCapabilityCatalog:
    version: str
    digest: str
    agents: Mapping[str, AgentSpec]
    workflows: Mapping[str, WorkflowSpec]
    native_tools: Mapping[str, ToolSpec]
    projections: CapabilityProjections

    def manifest(self) -> dict[str, Any]:
        """Safe operational manifest: no prompts, schemas, module paths, or callables."""

        return {
            "version": self.version,
            "digest": self.digest,
            "counts": {
                "agents": len(self.agents),
                "workflows": len(self.workflows),
                "native_tools": len(self.native_tools),
            },
            "route_names": sorted(self.projections.route_vocabulary),
            "billing_names": sorted(self.projections.billing_names),
        }


@dataclass(frozen=True, slots=True)
class CapabilityPolicyView:
    """Hot settings captured exactly once for a new run."""

    enabled: Mapping[str, bool]

    def flag(self, field: str, default: bool = True) -> bool:
        return bool(self.enabled.get(str(field), default))


@dataclass(frozen=True, slots=True)
class RunCapabilitySnapshot:
    """One run's static graph, admitted MCP overlay, settings, and omissions."""

    static: StaticCapabilityCatalog
    mcp_overlay: Mapping[str, ToolSpec]
    policy: CapabilityPolicyView
    omissions: tuple[Omission, ...] = ()

    @property
    def tools(self) -> Mapping[str, ToolSpec]:
        # MCP admission guarantees disjoint names; make a defensive merged projection.
        return frozen_mapping({**self.static.native_tools, **self.mcp_overlay})

    def tool(self, name: str) -> ToolSpec | None:
        key = str(name or "").strip()
        return self.mcp_overlay.get(key) or self.static.native_tools.get(key)

    def with_omissions(self, omissions: tuple[Omission, ...]) -> RunCapabilitySnapshot:
        """Return the next immutable policy projection for this run."""

        return RunCapabilitySnapshot(
            static=self.static,
            mcp_overlay=self.mcp_overlay,
            policy=self.policy,
            omissions=tuple(omissions),
        )


__all__ = [
    "CapabilityPolicyView",
    "CapabilityProjections",
    "RunCapabilitySnapshot",
    "StaticCapabilityCatalog",
    "frozen_mapping",
]
