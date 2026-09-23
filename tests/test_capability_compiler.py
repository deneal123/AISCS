"""S29 fail-fast capability graph and run-local admission contracts."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest

from service.domain.capabilities.agent_spec import AgentSpec
from service.domain.capabilities.compiler import (
    CATALOG_VERSION,
    CapabilityConfigurationError,
    compile_static_catalog,
)
from service.domain.capabilities.metrics import (
    METRIC_NAME,
    REASONS,
    STAGES,
    STATUSES,
    prometheus_samples,
    record,
    reset_for_tests,
)
from service.domain.capabilities.runtime import (
    admit_mcp_specs,
    build_run_capability_snapshot,
    initialize_static_catalog,
    reset_static_catalog_for_tests,
)
from service.domain.capabilities.tool_spec import ToolSpec
from service.domain.capabilities.workflow_spec import WorkflowSpec, WorkflowStep
from service.domain.run_context import PrivateRunResources, use_run_execution
from service.shared.agent_settings import use_settings


class _Agent:
    def __init__(self, settings: dict):
        self.settings = settings


def _agent(name: str = "general", **changes) -> AgentSpec:
    return replace(AgentSpec(name=name, label_ru="General", build=_Agent), **changes)


def _tool(name: str = "read_data", **changes) -> ToolSpec:
    return replace(ToolSpec(name=name, tool=SimpleNamespace(name=name)), **changes)


def _workflow(name: str = "workflow", agent: str = "general", **changes) -> WorkflowSpec:
    return replace(
        WorkflowSpec(
            name=name,
            label_ru="Workflow",
            steps=(WorkflowStep(agent=agent, instruction="Run"),),
        ),
        **changes,
    )


def _module(name: str, *, spec=None, specs=None) -> ModuleType:
    module = ModuleType(name)
    if spec is not None:
        module.SPEC = spec
    if specs is not None:
        module.SPECS = specs
    return module


def _compile(
    *,
    agents: tuple[AgentSpec, ...] = (_agent(),),
    workflows: tuple[WorkflowSpec, ...] = (),
    tools: tuple[ToolSpec, ...] = (),
    settings_fields: frozenset[str] = frozenset(),
    billable_contract: frozenset[str] | None = frozenset({"mcp_tool"}),
):
    modules: dict[str, ModuleType] = {}
    agent_sources = tuple(f"agent_{index}" for index in range(len(agents)))
    workflow_sources = tuple(f"workflow_{index}" for index in range(len(workflows)))
    tool_sources = ("tools",) if tools else ()
    modules.update(
        (path, _module(path, spec=spec)) for path, spec in zip(agent_sources, agents, strict=True)
    )
    modules.update(
        (path, _module(path, spec=spec))
        for path, spec in zip(workflow_sources, workflows, strict=True)
    )
    if tools:
        modules["tools"] = _module("tools", specs=tools)
    return compile_static_catalog(
        agent_sources=agent_sources,
        workflow_sources=workflow_sources,
        tool_sources=tool_sources,
        importer=modules.__getitem__,
        settings_fields=settings_fields,
        billable_contract=billable_contract,
    )


def _assert_code(code: str, call) -> None:
    with pytest.raises(CapabilityConfigurationError) as raised:
        call()
    assert raised.value.code == code
    assert str(raised.value) == f"capability configuration failed: {code}"


def test_full_native_catalog_compiles_to_safe_stable_manifest():
    first = compile_static_catalog()
    second = compile_static_catalog()

    assert first.version == CATALOG_VERSION
    assert first.digest == second.digest and len(first.digest) == 64
    assert list(first.agents) == list(second.agents)
    assert list(first.native_tools) == list(second.native_tools)
    assert set(first.manifest()) == {"version", "digest", "counts", "route_names", "billing_names"}
    rendered = repr(first.manifest()).lower()
    assert all(word not in rendered for word in ("prompt_hint", "schema", "module", "callable"))


def test_compiler_imports_each_declared_source_exactly_once():
    agent_module = _module("agent", spec=_agent())
    tool_module = _module("tools", specs=(_tool(),))
    modules = {"agent": agent_module, "tools": tool_module}
    calls: list[str] = []

    def importer(path: str) -> ModuleType:
        calls.append(path)
        return modules[path]

    compile_static_catalog(
        agent_sources=("agent",),
        workflow_sources=(),
        tool_sources=("tools",),
        importer=importer,
        settings_fields=frozenset(),
        billable_contract=frozenset({"mcp_tool"}),
    )

    assert calls == ["agent", "tools"]


@pytest.mark.parametrize(
    ("code", "call"),
    [
        (
            "import_failed",
            lambda: compile_static_catalog(
                agent_sources=("missing",),
                workflow_sources=(),
                tool_sources=(),
                importer=lambda _path: (_ for _ in ()).throw(ImportError("private")),
                settings_fields=frozenset(),
                billable_contract=None,
            ),
        ),
        (
            "invalid_spec",
            lambda: compile_static_catalog(
                agent_sources=("bad",),
                workflow_sources=(),
                tool_sources=(),
                importer=lambda path: _module(path, spec=object()),
                settings_fields=frozenset(),
                billable_contract=None,
            ),
        ),
        ("duplicate_name", lambda: _compile(agents=(_agent(), _agent()))),
        (
            "duplicate_name",
            lambda: _compile(workflows=(_workflow(name="general"),)),
        ),
        (
            "duplicate_name",
            lambda: _compile(tools=(_tool(), _tool())),
        ),
        (
            "reference_missing",
            lambda: _compile(workflows=(_workflow(agent="unknown"),)),
        ),
        (
            "settings_field_missing",
            lambda: _compile(agents=(_agent(enabled_field="missing_flag"),)),
        ),
        (
            "tool_name_mismatch",
            lambda: _compile(
                tools=(ToolSpec(name="declared", tool=SimpleNamespace(name="actual")),)
            ),
        ),
        (
            "billing_mismatch",
            lambda: _compile(billable_contract=frozenset()),
        ),
    ],
)
def test_compiler_rejects_static_configuration_with_bounded_code(code, call):
    _assert_code(code, call)


def test_catalog_and_run_snapshot_are_immutable():
    catalog = _compile(tools=(_tool(),))
    assert isinstance(catalog.agents, MappingProxyType)
    assert isinstance(catalog.native_tools, MappingProxyType)
    with pytest.raises(TypeError):
        catalog.agents["other"] = _agent("other")

    snapshot = build_run_capability_snapshot()
    assert isinstance(snapshot.mcp_overlay, MappingProxyType)
    assert isinstance(snapshot.policy.enabled, MappingProxyType)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cost_class", "unknown"),
        ("effect", "unknown"),
        ("grounding_roles", frozenset({"unknown"})),
        ("source", "mcp"),
    ],
)
def test_compiler_revalidates_tool_policy_values_even_for_prebuilt_specs(field, value):
    spec = _tool()
    object.__setattr__(spec, field, value)
    _assert_code("invalid_spec", lambda: _compile(tools=(spec,)))


def test_hot_settings_are_frozen_for_current_run_and_applied_to_next():
    catalog = initialize_static_catalog()
    field = next(
        spec.enabled_field
        for spec in (*catalog.agents.values(), *catalog.native_tools.values())
        if spec.enabled_field
    )

    with use_settings({field: False}):
        first = build_run_capability_snapshot()
    with use_settings({field: True}):
        second = build_run_capability_snapshot()

    assert first.policy.flag(field) is False
    assert second.policy.flag(field) is True
    assert first.policy.flag(field) is False


def test_run_context_uses_its_immutable_snapshot_without_cross_run_mcp_leakage(monkeypatch):
    dynamic = _tool("external_lookup", source="mcp", billing_name="mcp_tool")
    monkeypatch.setattr("service.infrastructure.mcp.runtime.current_specs", lambda: (dynamic,))
    with use_run_execution(PrivateRunResources()) as first:
        assert first.capabilities.tool("external_lookup") is dynamic

    monkeypatch.setattr("service.infrastructure.mcp.runtime.current_specs", lambda: ())
    with use_run_execution(PrivateRunResources()) as second:
        assert second.capabilities.tool("external_lookup") is None

    assert first.capabilities.tool("external_lookup") is dynamic


def test_tool_resolution_captures_typed_omissions_in_run_snapshot():
    from service.domain.capabilities.tool_registry import resolve_toolset

    tool = next(iter(initialize_static_catalog().native_tools.values())).tool
    with use_run_execution(PrivateRunResources()) as execution:
        resolved = resolve_toolset([tool], None, model_supports=False)

        assert execution.capabilities.omissions == tuple(resolved.omissions)
        assert execution.capabilities.omissions


def test_mcp_collision_and_invalid_specs_cannot_replace_native_tools():
    catalog = initialize_static_catalog()
    native_name, native = next(iter(catalog.native_tools.items()))
    collision = _tool(native_name, source="mcp", billing_name="mcp_tool")
    duplicate = _tool("external_lookup", source="mcp", billing_name="mcp_tool")
    invalid = _tool("Invalid-Name", source="mcp", billing_name="mcp_tool")

    admission = admit_mcp_specs((collision, duplicate, duplicate, invalid), catalog)
    snapshot = build_run_capability_snapshot(admission.accepted)

    assert snapshot.tool(native_name) is native
    assert [spec.name for spec in admission.accepted] == ["external_lookup"]
    assert admission.reasons == {
        "native_collision": 1,
        "duplicate_name": 1,
        "invalid_spec": 1,
    }


def test_process_catalog_is_compiled_once(monkeypatch):
    from service.domain.capabilities import runtime

    catalog = _compile()
    calls = 0

    def compile_once():
        nonlocal calls
        calls += 1
        return catalog

    reset_static_catalog_for_tests()
    monkeypatch.setattr(runtime, "compile_static_catalog", compile_once)
    try:
        assert initialize_static_catalog() is catalog
        assert initialize_static_catalog() is catalog
        assert calls == 1
    finally:
        reset_static_catalog_for_tests()


def test_declared_agent_build_failure_is_bounded(monkeypatch):
    from service.domain.capabilities import registry

    def broken_build(_settings):
        raise RuntimeError("private provider exception")

    catalog = _compile(agents=(replace(_agent(), build=broken_build),))
    monkeypatch.setattr(registry, "_catalog", lambda: catalog)

    with pytest.raises(registry.CapabilityBuildError) as raised:
        registry.build_agents({})

    assert raised.value.code == "capability_build"
    assert "private provider exception" not in str(raised.value)


def test_registry_metric_has_only_closed_labels():
    reset_for_tests()
    record("unknown-stage", "unknown-status", "private exception text")

    samples = prometheus_samples()

    assert samples == (
        (
            METRIC_NAME,
            {"stage": "run", "status": "failed", "reason": "invalid_spec"},
            1,
        ),
    )
    assert {labels["stage"] for _name, labels, _count in samples} <= STAGES
    assert {labels["status"] for _name, labels, _count in samples} <= STATUSES
    assert {labels["reason"] for _name, labels, _count in samples} <= REASONS


def test_production_pipeline_cannot_bypass_compiled_catalog():
    service_root = Path(__file__).parents[1] / "service"
    compatibility = {
        Path("domain/capabilities/registry.py"),
        Path("domain/capabilities/tool_registry.py"),
    }
    direct_calls = {"agent_specs", "workflow_specs", "tool_specs"}
    violations: list[str] = []

    for path in service_root.rglob("*.py"):
        relative = path.relative_to(service_root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in direct_calls
                and relative not in compatibility
            ):
                violations.append(f"{relative}:{node.lineno}:{node.func.id}")
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "importlib"
                and node.attr == "import_module"
                and relative != Path("domain/capabilities/compiler.py")
            ):
                violations.append(f"{relative}:{node.lineno}:import_module")

    assert violations == []


@pytest.mark.asyncio
async def test_static_configuration_failure_blocks_fastapi_startup(monkeypatch):
    from service import main as sidecar
    from service.domain.capabilities import runtime

    failure = CapabilityConfigurationError("billing_mismatch")
    monkeypatch.setattr(
        runtime, "initialize_static_catalog", lambda: (_ for _ in ()).throw(failure)
    )

    with pytest.raises(CapabilityConfigurationError, match="billing_mismatch"):
        async with sidecar._lifespan(sidecar.app):
            pytest.fail("lifespan must not start with an invalid static catalog")


@pytest.fixture(autouse=True)
def _restore_catalog_after_test():
    yield
    reset_static_catalog_for_tests()
