"""Реестр способностей агентского слоя.

Что снаружи видно: спека, реестр и производные представления. Всё, что раньше было
отдельным списком имён агентов, теперь выводится отсюда — и это проверяется тестом
`tests/test_new_agent_requires_one_place.py`, а не обещается комментарием.
"""

from .agent_spec import COST_CHEAP, COST_EXPENSIVE, COST_PAID, AgentSpec
from .catalog import RunCapabilitySnapshot, StaticCapabilityCatalog
from .compiler import CapabilityConfigurationError, compile_static_catalog
from .derived import (
    billing_names,
    confirm_default_names,
    decomposable_names,
    forced_allowlist,
    forced_by_input_type,
    modality_conflict,
    render_auto_route_enum,
    render_auto_routes,
    render_decompose_categories,
    required_input_type,
    route_labels,
    route_vocabulary,
    valid_router_tools,
)
from .registry import (
    CapabilityBuildError,
    agent_specs,
    build_agents,
    get_spec,
    get_workflow,
    workflow_specs,
)
from .runtime import get_static_catalog, initialize_static_catalog
from .workflow_spec import WorkflowSpec, WorkflowStep

__all__ = [
    "COST_CHEAP",
    "COST_EXPENSIVE",
    "COST_PAID",
    "AgentSpec",
    "CapabilityConfigurationError",
    "CapabilityBuildError",
    "RunCapabilitySnapshot",
    "StaticCapabilityCatalog",
    "agent_specs",
    "billing_names",
    "build_agents",
    "compile_static_catalog",
    "confirm_default_names",
    "decomposable_names",
    "forced_allowlist",
    "forced_by_input_type",
    "WorkflowSpec",
    "WorkflowStep",
    "get_spec",
    "get_static_catalog",
    "get_workflow",
    "workflow_specs",
    "initialize_static_catalog",
    "modality_conflict",
    "render_auto_route_enum",
    "render_auto_routes",
    "render_decompose_categories",
    "required_input_type",
    "route_labels",
    "route_vocabulary",
    "valid_router_tools",
]
