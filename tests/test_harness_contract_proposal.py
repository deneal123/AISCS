"""Real GigaChat contract regression; no loose JSON coercion or policy retry."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.application.harness import admission, proposal
from service.shared.harness_protocol import Continuation, ContractProposal, HarnessFailure

VALID = {
    "kind": "change",
    "criteria": [{"criterion_id": "script", "kind": "file", "target": "hello_world.py"}],
    "needs_clarification": False,
}
INVALID_GIGA = {
    "kind": "document",
    "criteria": [
        {
            "criterion_id": "verify_project",
            "kind": "command",
            "target": "./hello_world.py",
            "needs_clarification": False,
        }
    ],
    "needs_clarification": False,
}


def setup(monkeypatch, replies):
    current = SimpleNamespace(
        admission=SimpleNamespace(
            surface="ide",
            actions=("read", "write", "exec"),
            goal="Create hello_world.py",
        ),
        revision=0,
        state=None,
        continuation=Continuation(),
    )
    client = SimpleNamespace(current=current, load=AsyncMock(), exchange=AsyncMock())
    execution = SimpleNamespace(
        harness=client, task_state=None, bind_task_state=Mock(), provider_session=Mock()
    )
    invoke = AsyncMock(
        side_effect=[
            SimpleNamespace(
                response={
                    "choices": [
                        {
                            "message": {
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "contract",
                                        "type": "function",
                                        "function": {
                                            "name": proposal.CONTRACT_FUNCTION,
                                            "arguments": json.dumps(reply),
                                        },
                                    }
                                ],
                            }
                        }
                    ],
                }
            )
            for reply in replies
        ]
    )
    monkeypatch.setattr(admission, "invoke_model_call", invoke)
    return execution, client, invoke


@pytest.mark.asyncio
async def test_real_invalid_contract_is_repaired_once_before_sealing(monkeypatch):
    execution, client, invoke = setup(monkeypatch, [INVALID_GIGA, VALID])
    await admission.seal_harness(execution, "GigaChat-3-Lightning")
    assert invoke.await_count == 2
    for call in invoke.await_args_list:
        assert call.kwargs["model"] == "GigaChat-3-Lightning"
        assert call.kwargs["kind"] == "meta_usage"
        assert call.kwargs["provider_session"] is execution.provider_session
        assert call.kwargs["messages"][0]["role"] == "system"
    client.exchange.assert_awaited_once()
    assert client.exchange.await_args.kwargs["opcode"] == "seal"
    assert client.exchange.await_args.kwargs["proposal"] == ContractProposal.model_validate(VALID)


@pytest.mark.asyncio
async def test_invalid_contract_twice_blocks_without_seal_or_more_paid_calls(monkeypatch):
    execution, client, invoke = setup(monkeypatch, [INVALID_GIGA, INVALID_GIGA])
    with pytest.raises(HarnessFailure, match="task_contract_invalid"):
        await admission.seal_harness(execution, "GigaChat-3-Lightning")
    assert invoke.await_count == 2
    client.exchange.assert_not_awaited()
    execution.bind_task_state.assert_not_called()


@pytest.mark.asyncio
async def test_backend_policy_denial_is_never_repaired_or_overridden(monkeypatch):
    execution, client, invoke = setup(monkeypatch, [VALID])
    client.exchange.side_effect = HarnessFailure("task_permission_denied")
    with pytest.raises(HarnessFailure, match="task_permission_denied"):
        await admission.seal_harness(execution, "GigaChat-3-Lightning")
    assert invoke.await_count == 1
    execution.bind_task_state.assert_not_called()


@pytest.mark.asyncio
async def test_refinement_reviews_question_once_without_exceeding_admission_limit(monkeypatch):
    from service.settings import config

    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    questioned = {**VALID, "needs_clarification": True, "question": "Как написать этот код?"}
    execution, client, invoke = setup(monkeypatch, [questioned, VALID])
    await admission.seal_harness(execution, "test-model")
    assert invoke.await_count == 2
    assert "реализацию выбирает агент" in invoke.await_args.kwargs["messages"][-1]["content"]
    assert client.exchange.await_args.kwargs["proposal"].needs_clarification is False


@pytest.mark.asyncio
async def test_real_ambiguity_after_review_still_requires_user_decision(monkeypatch):
    from service.application.harness import clarification
    from service.settings import config

    monkeypatch.setattr(config.agents, "harness_refinement_enabled", True)
    questioned = {**VALID, "needs_clarification": True, "question": "Какой формат файла выбрать?"}
    execution, client, invoke = setup(monkeypatch, [questioned, questioned])
    park = AsyncMock(side_effect=HarnessFailure("user_decision_required"))
    monkeypatch.setattr(clarification, "park", park)
    with pytest.raises(HarnessFailure, match="user_decision_required"):
        await admission.seal_harness(execution, "test-model")
    assert invoke.await_count == 2 and park.await_count == 1
    client.exchange.assert_not_awaited()


@pytest.mark.parametrize(
    "invalid",
    [
        {**VALID, "kind": "document"},
        {**VALID, "criteria": [{"criterion_id": "verify_project", "kind": "command"}]},
        {**VALID, "evidence": "already done"},
    ],
)
def test_surface_reserved_id_and_extra_fields_are_rejected_not_scrubbed(invalid):
    with pytest.raises(ValueError):
        proposal.parse_proposal(json.dumps(invalid), SimpleNamespace(surface="ide"))


@pytest.mark.parametrize("provider", ["gigachat", "routerai", "openai"])
def test_contract_function_compiles_without_a_second_provider_dialect(provider):
    from service.domain.client.protocol import (
        GIGACHAT_TOOL_CAPABILITIES,
        OPENAI_TOOL_CAPABILITIES,
        compile_toolset,
    )

    tool = proposal.contract_tool(SimpleNamespace(surface="ide"))
    compiled = compile_toolset(
        [tool],
        provider=provider,
        capabilities=GIGACHAT_TOOL_CAPABILITIES
        if provider == "gigachat"
        else OPENAI_TOOL_CAPABILITIES,
        tool_choice={"type": "function", "function": {"name": proposal.CONTRACT_FUNCTION}},
    )
    assert compiled.canonical_names == (proposal.CONTRACT_FUNCTION,)


def test_plain_prose_or_wrong_function_cannot_become_a_contract():
    for message in [
        {"content": json.dumps(VALID)},
        {
            "tool_calls": [
                {
                    "function": {
                        "name": "ide_write_file",
                        "arguments": json.dumps(VALID),
                    }
                }
            ]
        },
    ]:
        with pytest.raises(ValueError, match="contract_function_required"):
            proposal.response_arguments({"choices": [{"message": message}]})


def test_contract_schema_exposes_existing_server_identifier_and_count_limits():
    from service.shared.task_contract import TaskCriterion

    properties = proposal.contract_tool(SimpleNamespace(surface="ide"))["function"]["parameters"][
        "properties"
    ]
    criteria = properties["criteria"]
    runtime = ContractProposal.model_json_schema()["properties"]["criteria"]
    assert criteria["minItems"] == runtime["minItems"]
    assert criteria["maxItems"] == runtime["maxItems"]
    identifier = criteria["items"]["properties"]["criterion_id"]
    assert (
        identifier["pattern"]
        == TaskCriterion.model_json_schema()["properties"]["criterion_id"]["pattern"]
    )


@pytest.mark.parametrize(
    "needs,question,reason",
    [
        (False, "Как написать код?", "contract_question_unexpected"),
        (True, "", "contract_question_required"),
    ],
)
def test_question_inconsistency_has_specific_repair_reason(needs, question, reason):
    invalid = {**VALID, "needs_clarification": needs, "question": question}
    with pytest.raises(ValueError, match=reason):
        proposal.parse_proposal(json.dumps(invalid), SimpleNamespace(surface="ide"))
