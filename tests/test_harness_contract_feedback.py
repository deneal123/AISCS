"""Исправление получает конкретную закрытую причину, но не validation input."""

import json
from types import SimpleNamespace

import pytest

from service.application.harness.feedback import contract_feedback
from service.application.harness.proposal import parse_proposal
from tests.test_harness_contract_proposal import VALID, setup


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("criterion_id", "PRIVATE.INVALID", "criterion_id"),
        ("target", "./PRIVATE_SOURCE", "target"),
    ],
)
def test_validation_feedback_exposes_only_field_rule(field, value, expected):
    arguments = json.loads(json.dumps(VALID))
    arguments["criteria"][0][field] = value
    with pytest.raises(ValueError) as raised:
        parse_proposal(json.dumps(arguments), SimpleNamespace(surface="ide"))
    feedback = contract_feedback(raised.value)
    assert expected in feedback and "PRIVATE" not in feedback
    if field == "target":
        assert "Удаляй начальный ./" in feedback
        assert "Сохрани имя запрошенного файла" in feedback
    assert contract_feedback(ValueError("PRIVATE_INTERNAL_DETAIL")) == ""


def test_one_repair_reports_all_known_field_errors_without_raw_values():
    arguments = {
        **VALID,
        "criteria": [
            {"criterion_id": "PRIVATE.INVALID", "kind": "file", "target": "./PRIVATE_SOURCE"}
        ],
    }
    with pytest.raises(ValueError) as raised:
        parse_proposal(json.dumps(arguments), SimpleNamespace(surface="ide"))
    feedback = contract_feedback(raised.value)
    assert "criterion_id" in feedback and "target" in feedback and "PRIVATE" not in feedback


@pytest.mark.asyncio
async def test_question_protocol_repair_remains_one_call_and_does_not_force_decision(monkeypatch):
    from service.application.harness import admission

    invalid = {**VALID, "question": "PRIVATE_QUESTION"}
    execution, client, invoke = setup(monkeypatch, [invalid, VALID])
    await admission.seal_harness(execution, "test-model")
    assert invoke.await_count == 2
    feedback = invoke.await_args.kwargs["messages"][-1]["content"]
    assert "При needs_clarification=false question должен быть пустой строкой" in feedback
    assert "Если действительно требуется решение пользователя" in feedback
    assert "PRIVATE" not in feedback
    client.exchange.assert_awaited_once()
