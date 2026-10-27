"""Одна оплачиваемая рекомендация для штатного repair, без новых инструментов."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from service.domain.execution.grounding import GroundingFailureCode, GroundingState
from service.domain.runners.harness import refinement
from service.settings import config
from service.shared.harness_protocol import Continuation, HarnessFailure


def scenario():
    usage = SimpleNamespace(receipts=[SimpleNamespace(kind="chat", receipt_id=str(uuid4()))])
    execution = SimpleNamespace(
        harness=SimpleNamespace(
            current=SimpleNamespace(
                continuation=Continuation(provider={"provider": "local", "model": "test"})
            )
        ),
        grounding=SimpleNamespace(
            state=GroundingState.REPAIR,
            failure_code=GroundingFailureCode.MISSING_CALL,
            eligible_names={"ide_read_file"},
        ),
        task_state=SimpleNamespace(contract=SimpleNamespace(goal="Прочитай файл"), evidence=[]),
        cancelled=False,
        usage=usage,
    )
    return SimpleNamespace(
        execution=execution, max_tokens=1000, openai_tools=[{"function": {"name": "ide_read_file"}}]
    )


def model_result(proposal, *, reason="stop"):
    return SimpleNamespace(
        call_id=str(uuid4()),
        finish_reason=reason,
        response=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(proposal, ensure_ascii=False))
                )
            ]
        ),
    )


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai", "local"])
def test_proposal_tool_compiles_through_existing_provider_protocol(provider):
    from service.domain.client.protocol import (
        GIGACHAT_TOOL_CAPABILITIES,
        OPENAI_TOOL_CAPABILITIES,
        compile_toolset,
    )
    from service.shared.harness_refinement import PROPOSAL_TOOL, proposal_tool

    capabilities = (
        GIGACHAT_TOOL_CAPABILITIES if provider == "gigachat" else OPENAI_TOOL_CAPABILITIES
    )
    result = compile_toolset(
        [proposal_tool()],
        provider=provider,
        capabilities=capabilities,
        tool_choice={"type": "function", "function": {"name": PROPOSAL_TOOL}},
    )
    assert result.canonical_names == (PROPOSAL_TOOL,)


@pytest.mark.asyncio
async def test_proposal_uses_same_provider_and_one_bounded_meta_call(monkeypatch):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    state, calls = scenario(), []

    async def invoke(call, **kwargs):
        calls.append(kwargs)
        return model_result(
            {
                "instruction": "Вызови обязательный инструмент до ответа.",
                "tools": [{"name": "ide_read_file", "advice": "Читай целевой файл."}],
            }
        )

    monkeypatch.setattr(refinement, "invoke_model_call", invoke)
    result = await refinement.propose_refinement(state)
    assert result.probe_step == 1 and not result.adopted
    assert result.baseline_operation == state.execution.usage.receipts[0].receipt_id
    assert len(calls) == 1 and calls[0]["pin_provider"] == "local"
    assert calls[0]["model"] == "test" and calls[0]["max_tokens"] == 512
    assert calls[0]["kind"] == "meta_usage"
    assert "не расширяет полномочия" in refinement.render_refinement(result.proposal)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["disabled", "cancelled", "not_repair", "tool_failure"])
async def test_no_extra_dispatch_outside_single_eligible_repair(monkeypatch, case):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", case != "disabled")
    state = scenario()
    if case == "cancelled":
        state.execution.cancelled = True
    elif case == "not_repair":
        state.execution.grounding.state = GroundingState.SATISFIED
    elif case == "tool_failure":
        state.execution.grounding.failure_code = GroundingFailureCode.TOOL_FAILURE

    async def forbidden(*args, **kwargs):
        raise AssertionError("unexpected_meta_dispatch")

    monkeypatch.setattr(refinement, "invoke_model_call", forbidden)
    assert await refinement.propose_refinement(state) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unknown_tool", "invalid", "truncated", "unknown_cost"])
async def test_bad_proposal_never_becomes_guidance(monkeypatch, case):
    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    state = scenario()

    async def invoke(*args, **kwargs):
        if case == "unknown_cost":
            raise HarnessFailure("cost_unknown")
        proposal = {"instruction": "Прочитай файл", "tools": []}
        if case == "unknown_tool":
            proposal["tools"] = [{"name": "host_shell", "advice": "Недоступный инструмент"}]
        if case == "invalid":
            proposal["new_authority"] = True
        return model_result(proposal, reason="length" if case == "truncated" else "stop")

    monkeypatch.setattr(refinement, "invoke_model_call", invoke)
    if case == "unknown_cost":
        with pytest.raises(HarnessFailure, match="cost_unknown"):
            await refinement.propose_refinement(state)
    else:
        assert await refinement.propose_refinement(state) is None
