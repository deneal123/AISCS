"""Обязательное чтение определяется контрактом, а не только авто-маршрутом."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from service.domain.capabilities.tools.disclosure import DisclosureResult, disclose
from service.domain.capabilities.tools.spec import ToolSet
from service.domain.execution.context import (
    GroundingRequirement,
    PrivateRunResources,
    use_run_execution,
)
from service.domain.execution.grounding import GroundingState
from service.domain.runners.chat.disclosure import ToolSelectionController
from tests.test_task_contract import evidence, state
from tests.test_tool_disclosure import _async, _overlay, _response


def analysis(*, proof=None, revision="r1"):
    initial = state()
    return initial.advance(
        contract={
            **initial.contract.model_dump(mode="json"),
            "kind": "analysis",
            "actions": ["read"],
            "criteria": [
                {"criterion_id": "source", "kind": "read", "target": "src/hello_world.py"}
            ],
        },
        evidence=[proof] if proof else [],
        source_revision=revision,
    )


def tools(*names):
    return ToolSet(tools=[{"type": "function", "function": {"name": name}} for name in names])


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", ["r1", "r2"])
@pytest.mark.parametrize("has_proof", [False, True])
async def test_sealed_read_is_mandatory_until_current_receipt(monkeypatch, revision, has_proof):
    import service.domain.runners.chat.disclosure as module

    offered = tools("ide_read_file", "ide_finish_task")
    monkeypatch.setattr(module, "disclose", AsyncMock(return_value=DisclosureResult(offered)))
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        execution.bind_task_state(
            analysis(proof=evidence(kind="read") if has_proof else None, revision=revision)
        )
        execution.harness = SimpleNamespace()
        selector = ToolSelectionController(
            offered, "Прочитай исходник", "general", None, "test", execution
        )
        await selector.select(stage=1, remaining_prompt_tokens=None)
        required = not has_proof or revision != "r1"
        assert execution.grounding.required is required
        assert execution.grounding.blocks_output is required
        assert execution.policy.flag("contract_read_required") is required
        if required:
            assert not execution.grounding.accepts("ide_finish_task")
            assert execution.grounding.accepts("ide_read_file")
            execution.grounding.begin_round()
            assert execution.grounding.finish_model_round([]) is GroundingState.REPAIR


@pytest.mark.asyncio
@pytest.mark.parametrize("skip", ["no_harness", "no_ide", "fresh_data", "cancelled"])
async def test_read_contract_does_not_replace_other_policy_or_extend_scope(monkeypatch, skip):
    import service.domain.runners.chat.disclosure as module

    offered = tools("ide_read_file")
    monkeypatch.setattr(module, "disclose", AsyncMock(return_value=DisclosureResult(offered)))
    workspace = None if skip == "no_ide" else {"ide_context": {}}
    with use_run_execution(PrivateRunResources(workspace_ref=workspace)) as execution:
        execution.bind_task_state(analysis())
        execution.harness = None if skip == "no_harness" else SimpleNamespace()
        execution.cancelled = skip == "cancelled"
        original = (
            GroundingRequirement.FRESH_DATA if skip == "fresh_data" else GroundingRequirement.NONE
        )
        execution.policy.grounding_reason = original
        selector = ToolSelectionController(
            offered, "Прочитай исходник", "general", None, "test", execution
        )
        await selector.select(stage=1, remaining_prompt_tokens=None)
        assert execution.policy.grounding_reason is original
        assert not execution.policy.flag("contract_read_required")


@pytest.mark.asyncio
@pytest.mark.parametrize("preferred", ["ide_finish_task", "ask_user_question"])
async def test_selector_cannot_replace_required_read_with_report_or_question(
    monkeypatch, preferred
):
    import service.domain.client as client

    _overlay(monkeypatch, mode="enforce", minimum=1)
    monkeypatch.setattr(client, "list_qualified_models", lambda: _async(["gpt-4o-mini"]))
    monkeypatch.setattr(
        client,
        "create_chat_completion",
        lambda **kwargs: _async(
            _response('{"tools":["' + preferred + '"],"preferred_tool":"' + preferred + '"}')
        ),
    )
    offered = tools("ide_read_file", preferred)
    with use_run_execution(PrivateRunResources()) as execution:
        execution.policy.grounding_reason = GroundingRequirement.WORKSPACE_EXPLICIT
        execution.policy.set_flag("contract_read_required", True)
        result = await disclose(
            offered,
            question="Прочитай файл",
            agent_name="general",
            context=None,
            preferred_model="gpt-4o-mini",
            stage=1,
            executed=[],
            execution=execution,
        )
        assert result.toolset is offered
        assert result.preferred_tool is None
        assert result.event.metadata["tool_disclosure"]["fallback_reason"] == "invalid_selection"


@pytest.mark.asyncio
async def test_unavailable_read_cannot_be_resurrected_by_contract(monkeypatch):
    import service.domain.runners.chat.disclosure as module

    offered = tools("ide_finish_task")
    monkeypatch.setattr(module, "disclose", AsyncMock(return_value=DisclosureResult(offered)))
    with use_run_execution(PrivateRunResources(workspace_ref={"ide_context": {}})) as execution:
        execution.bind_task_state(analysis())
        execution.harness = SimpleNamespace()
        selector = ToolSelectionController(
            offered, "Прочитай исходник", "general", None, "test", execution
        )
        selected = await selector.select(stage=1, remaining_prompt_tokens=None)
        assert selected.toolset is offered
        assert execution.grounding.state is GroundingState.FAILED
        assert execution.grounding.failure_code.value == "no_eligible_tools"
        assert not execution.grounding.eligible_names
