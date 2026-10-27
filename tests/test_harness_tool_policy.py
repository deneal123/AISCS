"""Модели не предлагают инструменты, которые этот harness заведомо не исполнит."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.capabilities.tools import harness, registry
from service.domain.capabilities.tools.spec import ToolSpec
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.domain.runners.harness.tools import execute_harness_tool
from service.shared.harness_protocol import HarnessFailure


@pytest.mark.parametrize(
    "surface,actions,expected",
    [
        ("ide", ("read", "write", "exec"), {"ide_read_file", "ide_write_file", "ide_run_command"}),
        ("ide", ("read",), {"ide_read_file"}),
        ("pdf", ("read", "document"), {"tex_propose_structure"}),
    ],
)
def test_registry_filters_after_mcp_overlay_and_preserves_visible_omissions(
    monkeypatch, surface, actions, expected
):
    names = [
        "ide_read_file",
        "ide_write_file",
        "ide_run_command",
        "tex_propose_structure",
        "open_webpage",
        "ws_run",
        "tex_compile",
    ]
    tools = [SimpleNamespace(name=name) for name in names]
    mcp = ToolSpec(
        name="mcp_unknown_effect", tool=SimpleNamespace(name="mcp_unknown_effect"), source="mcp"
    )
    monkeypatch.setattr(registry, "tool_specs", lambda: {mcp.name: mcp})
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = SimpleNamespace(
            current=SimpleNamespace(admission=SimpleNamespace(surface=surface, actions=actions))
        )
        selected = registry.resolve_toolset(tools, None)
        assert {tool.name for tool in selected.tools} == expected
        assert {item.tool for item in selected.omissions} == set(names + [mcp.name]) - expected
        assert {item.reason for item in selected.omissions} == {"task_policy"}
        assert execution.capabilities.omissions == tuple(selected.omissions)


def test_ordinary_chat_toolset_is_not_restricted_by_harness_policy(monkeypatch):
    tools = [SimpleNamespace(name="open_webpage")]
    monkeypatch.setattr(registry, "tool_specs", dict)
    with use_run_execution(PrivateRunResources()):
        selected = registry.resolve_toolset(tools, None)
        assert selected.tools == tools and selected.omissions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["open_webpage", "tex_propose_structure", "ide_run_command"])
async def test_direct_invocation_cannot_bypass_offer_policy(name):
    invoke = AsyncMock()
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = SimpleNamespace(
            failure=None,
            current=SimpleNamespace(admission=SimpleNamespace(surface="ide", actions=("read",))),
        )
        with pytest.raises(HarnessFailure, match="task_permission_denied"):
            await execute_harness_tool(SimpleNamespace(name=name), invoke)
    invoke.assert_not_awaited()


def test_adapter_policy_is_explicit_not_a_trusted_name_prefix():
    admission = SimpleNamespace(surface="ide", actions=("read", "write", "exec"))
    assert harness.unavailable_reason(admission, "ide_unreviewed_external_effect")
    assert harness.tool_action("ide_unreviewed_external_effect") is None


def test_local_contract_cannot_expand_server_admission():
    admission = SimpleNamespace(surface="ide", actions=("read",))
    assert harness.unavailable_reason(admission, "ide_write_file", actions=("read", "write"))


def test_sealed_analysis_is_read_only_even_when_admission_allowed_edits(monkeypatch):
    from tests.test_harness_reconciliation import current

    saved = current().state
    contract = {
        **saved.contract.model_dump(mode="json"),
        "kind": "analysis",
        "actions": ["read"],
        "criteria": [{"criterion_id": "source", "kind": "read", "target": "a.py"}],
    }
    state = saved.advance(contract=contract)
    monkeypatch.setattr(registry, "tool_specs", dict)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.harness = SimpleNamespace(current=current())
        execution.bind_task_state(state)
        selected = registry.resolve_toolset(
            [SimpleNamespace(name=name) for name in ["ide_read_file", "ide_write_file"]], None
        )
        assert [tool.name for tool in selected.tools] == ["ide_read_file"]
        assert selected.omissions[0].tool == "ide_write_file"
