"""Приватная привязка среды не попадает в сообщения, schema или task_result."""

import json
from uuid import uuid4

import pytest

from service.application.harness.proposal import contract_messages, contract_tool, parse_proposal
from service.shared.harness_protocol import Admission
from service.shared.task_contract import CompletionVerifier
from tests.test_task_contract import state


def test_admission_binding_is_private_and_cannot_be_proposed_by_the_model():
    private = "private-workspace-identity"
    accepted = Admission(
        task_id=str(uuid4()),
        project_id="project",
        generation="generation",
        workspace_id=private,
        surface="ide",
        goal="Прочитай a.py",
        source_revision="revision",
        actions=["read"],
        credit_limit=0,
        reservation_id=str(uuid4()),
    )
    assert private not in repr(accepted)
    assert private not in json.dumps(contract_messages(accepted))
    assert "workspace_id" not in json.dumps(contract_tool(accepted))
    assert private not in json.dumps(CompletionVerifier.evaluate(state()))
    with pytest.raises(ValueError):
        parse_proposal(
            json.dumps(
                {
                    "kind": "analysis",
                    "criteria": [{"criterion_id": "source", "kind": "read", "target": "a.py"}],
                    "workspace_id": private,
                }
            ),
            accepted,
        )
