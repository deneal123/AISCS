"""Fail-fast compiler for built-in agents, workflows, and tools."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Callable, Iterable, Sequence
from types import ModuleType
from typing import Any

from service.contracts import BILLABLE_TOOLS, LEGACY_BILLING_NAMES
from service.settings import AgentsConfig

from .agent_spec import COST_CLASSES, AgentSpec
from .catalog import CapabilityProjections, StaticCapabilityCatalog, frozen_mapping
from .metrics import record
from .sources import AGENT_SOURCES, DYNAMIC_BILLING_NAMES, TOOL_SOURCES, WORKFLOW_SOURCES
from .tool_spec import GROUNDING_ROLES, TOOL_EFFECTS, ToolSpec
from .workflow_spec import WorkflowSpec

CATALOG_VERSION = "s29.v1"
ERROR_CODES = frozenset(
    {
        "import_failed",
        "invalid_spec",
        "duplicate_name",
        "reference_missing",
        "settings_field_missing",
        "tool_name_mismatch",
        "billing_mismatch",
    }
)
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
Importer = Callable[[str], ModuleType]


class CapabilityConfigurationError(RuntimeError):
    """A bounded startup failure; source paths and exception text stay private."""

    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "invalid_spec"
        super().__init__(f"capability configuration failed: {self.code}")


def _fail(code: str) -> None:
    record("compile", "failed", code)
    raise CapabilityConfigurationError(code)


def _import_sources(paths: Sequence[str], importer: Importer) -> tuple[ModuleType, ...]:
    modules: list[ModuleType] = []
    for path in paths:
        try:
            module = importer(path)
        except Exception:  # noqa: BLE001 - startup error must expose only a bounded code
            _fail("import_failed")
        if not isinstance(module, ModuleType):
            _fail("import_failed")
        modules.append(module)
    return tuple(modules)


def _valid_name(value: Any) -> bool:
    return isinstance(value, str) and bool(_NAME.fullmatch(value))


def _load_single(
    paths: Sequence[str], expected: type, importer: Importer
) -> tuple[AgentSpec | WorkflowSpec, ...]:
    values: list[AgentSpec | WorkflowSpec] = []
    for module in _import_sources(paths, importer):
        spec = getattr(module, "SPEC", None)
        if not isinstance(spec, expected):
            _fail("invalid_spec")
        values.append(spec)
    return tuple(values)


def _load_tools(paths: Sequence[str], importer: Importer) -> tuple[ToolSpec, ...]:
    values: list[ToolSpec] = []
    for module in _import_sources(paths, importer):
        specs = getattr(module, "SPECS", None)
        if isinstance(specs, (str, bytes)) or not isinstance(specs, Iterable):
            _fail("invalid_spec")
        for spec in specs:
            if not isinstance(spec, ToolSpec):
                _fail("invalid_spec")
            values.append(spec)
    return tuple(values)


def _unique(values: Sequence[Any], *, shared: set[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    occupied = shared if shared is not None else set()
    for spec in values:
        name = getattr(spec, "name", None)
        if not _valid_name(name):
            _fail("invalid_spec")
        if name in occupied or name in result:
            _fail("duplicate_name")
        result[name] = spec
    occupied.update(result)
    return result


def _validate_agents(agents: dict[str, AgentSpec], settings_fields: frozenset[str]) -> None:
    for spec in agents.values():
        if not callable(spec.build) or not isinstance(spec.label_ru, str):
            _fail("invalid_spec")
        if spec.cost_class not in COST_CLASSES:
            _fail("invalid_spec")
        if spec.enabled_field and spec.enabled_field not in settings_fields:
            _fail("settings_field_missing")


def _validate_workflows(
    workflows: dict[str, WorkflowSpec],
    agents: dict[str, AgentSpec],
    settings_fields: frozenset[str],
) -> None:
    for spec in workflows.values():
        if spec.cost_class not in COST_CLASSES or not spec.steps:
            _fail("invalid_spec")
        if spec.enabled_field and spec.enabled_field not in settings_fields:
            _fail("settings_field_missing")
        if any(not _valid_name(step.agent) or step.agent not in agents for step in spec.steps):
            _fail("reference_missing")


def _validate_tools(tools: dict[str, ToolSpec], settings_fields: frozenset[str]) -> None:
    for spec in tools.values():
        if str(getattr(spec.tool, "name", "") or "") != spec.name:
            _fail("tool_name_mismatch")
        if spec.cost_class not in COST_CLASSES:
            _fail("invalid_spec")
        if spec.effect not in TOOL_EFFECTS or set(spec.grounding_roles) - GROUNDING_ROLES:
            _fail("invalid_spec")
        if spec.source not in {"native", "workspace"}:
            _fail("invalid_spec")
        if spec.enabled_field and spec.enabled_field not in settings_fields:
            _fail("settings_field_missing")


def _billing_names(agents: dict[str, AgentSpec], tools: dict[str, ToolSpec]) -> frozenset[str]:
    names = {spec.billing_name for spec in agents.values() if spec.billing_name}
    names.update(spec.billing_name for spec in tools.values() if spec.billing_name)
    names.update(DYNAMIC_BILLING_NAMES)
    return frozenset(names)


def _projections(
    agents: dict[str, AgentSpec], workflows: dict[str, WorkflowSpec], tools: dict[str, ToolSpec]
) -> CapabilityProjections:
    route_specs = (*agents.values(), *workflows.values())
    prompt_routes = tuple(
        spec
        for spec in route_specs
        if getattr(spec, "prompt_hint", "") and (not isinstance(spec, AgentSpec) or spec.routable)
    )
    forced_before: dict[str, str] = {}
    forced_after: dict[str, str] = {}
    for spec in agents.values():
        target = forced_before if spec.input_type_beats_toggles else forced_after
        for input_type in spec.forced_by_input_type:
            if input_type in target:
                _fail("duplicate_name")
            target[input_type] = spec.name
    decomposable = tuple(spec.name for spec in agents.values() if spec.decomposable)
    route_vocabulary = frozenset(
        {spec.name for spec in agents.values() if spec.routable} | set(workflows)
    )
    forced = frozenset(spec.name for spec in agents.values() if spec.forceable)
    return CapabilityProjections(
        route_vocabulary=route_vocabulary,
        forced_allowlist=forced,
        valid_router_tools=forced | {"none"},
        decomposable_names=decomposable,
        route_labels=frozen_mapping({spec.name: spec.label_ru for spec in route_specs}),
        billing_names=_billing_names(agents, tools),
        tool_billing_names=frozen_mapping(
            {spec.name: spec.billing_name for spec in tools.values() if spec.billing_name}
        ),
        confirm_default_names=frozenset(
            spec.name for spec in route_specs if spec.confirm_by_default
        ),
        required_input_types=frozen_mapping(
            {
                spec.name: spec.requires_input_type
                for spec in agents.values()
                if spec.requires_input_type
            }
        ),
        forced_before_toggles=frozen_mapping(forced_before),
        forced_after_toggles=frozen_mapping(forced_after),
        auto_routes="\n".join(f"- {spec.name} — {spec.prompt_hint}" for spec in prompt_routes),
        auto_route_enum="|".join(spec.name for spec in prompt_routes),
        decompose_categories=", ".join(decomposable),
    )


def _digest_payload(
    agents: dict[str, AgentSpec], workflows: dict[str, WorkflowSpec], tools: dict[str, ToolSpec]
) -> dict[str, Any]:
    from service.domain.documents.profile_contract import (
        DOCUMENT_PROFILE_CONTRACT_VERSION,
        DOCUMENT_PROFILE_IDS,
    )

    return {
        "version": CATALOG_VERSION,
        "document_profiles": {
            "version": DOCUMENT_PROFILE_CONTRACT_VERSION,
            "ids": list(DOCUMENT_PROFILE_IDS),
        },
        "agents": [
            {
                "name": spec.name,
                "route": [spec.routable, spec.forceable, spec.decomposable],
                "cost": spec.cost_class,
                "billing": spec.billing_name,
                "confirm": spec.confirm_by_default,
                "input": spec.requires_input_type,
                "forced": list(spec.forced_by_input_type),
                "enabled": spec.enabled_field,
            }
            for spec in agents.values()
        ],
        "workflows": [
            {
                "name": spec.name,
                "steps": [step.agent for step in spec.steps],
                "cost": spec.cost_class,
                "confirm": spec.confirm_by_default,
                "enabled": spec.enabled_field,
            }
            for spec in workflows.values()
        ],
        "tools": [
            {
                "name": spec.name,
                "source": spec.source,
                "billing": spec.billing_name,
                "cost": spec.cost_class,
                "effect": spec.effect,
                "grounding": sorted(spec.grounding_roles),
                "enabled": spec.enabled_field,
            }
            for spec in tools.values()
        ],
    }


def compile_static_catalog(
    *,
    agent_sources: Sequence[str] = AGENT_SOURCES,
    workflow_sources: Sequence[str] = WORKFLOW_SOURCES,
    tool_sources: Sequence[str] = TOOL_SOURCES,
    importer: Importer = importlib.import_module,
    settings_fields: frozenset[str] | None = None,
    billable_contract: frozenset[str] | None = BILLABLE_TOOLS,
) -> StaticCapabilityCatalog:
    """Compile and validate the complete built-in graph or raise a bounded error."""

    agents_tuple = _load_single(tuple(agent_sources), AgentSpec, importer)
    workflows_tuple = _load_single(tuple(workflow_sources), WorkflowSpec, importer)
    tools_tuple = _load_tools(tuple(tool_sources), importer)
    route_names: set[str] = set()
    agents = _unique(agents_tuple, shared=route_names)
    workflows = _unique(workflows_tuple, shared=route_names)
    tools = _unique(tools_tuple)
    declared_fields = (
        frozenset(AgentsConfig.model_fields) if settings_fields is None else settings_fields
    )
    _validate_agents(agents, declared_fields)
    _validate_workflows(workflows, agents, declared_fields)
    _validate_tools(tools, declared_fields)
    projections = _projections(agents, workflows, tools)
    expected_billing = (
        frozenset(billable_contract) - LEGACY_BILLING_NAMES
        if billable_contract is not None
        else None
    )
    if expected_billing is not None and projections.billing_names != expected_billing:
        _fail("billing_mismatch")
    encoded = json.dumps(
        _digest_payload(agents, workflows, tools),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    catalog = StaticCapabilityCatalog(
        version=CATALOG_VERSION,
        digest=hashlib.sha256(encoded).hexdigest(),
        agents=frozen_mapping(agents),
        workflows=frozen_mapping(workflows),
        native_tools=frozen_mapping(tools),
        projections=projections,
    )
    record("compile", "ok")
    return catalog


__all__ = [
    "CATALOG_VERSION",
    "ERROR_CODES",
    "CapabilityConfigurationError",
    "compile_static_catalog",
]
