"""Предконтрактная пауза: проверка receipt и границы полномочий без настоящей БД."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from service.services.chat.persistence.harness.admission_checkpoint import (
    require_answered,
    save_admission_checkpoint,
)
from service.services.chat.persistence.harness.runtime import _sealed_state
from service.shared.harness_protocol import Continuation, Exchange, HarnessFailure, Snapshot
from tests.test_harness_runtime_contract import admission

QUESTION = "Как назвать файл?"


def continuation():
    return Continuation(
        provider={"provider": "gigachat", "model": "test"},
        next_step=1,
        admission_active_ms=50,
        phase="admitting",
        messages=[
            {"role": "user", "content": "Запрос: исходная цель"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "question",
                        "function": {
                            "name": "ask_user_question",
                            "arguments": json.dumps(
                                {
                                    "prompt": QUESTION,
                                    "choices": [],
                                }
                            ),
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "question", "content": '{"awaiting_user":true}'},
        ],
    )


def proof():
    return {
        "request": {"provider": "gigachat", "model": "test"},
        "receipt": {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "submit_task_contract",
                            "arguments": json.dumps(
                                {
                                    "kind": "change",
                                    "criteria": [
                                        {"criterion_id": "file", "kind": "file", "target": "a.py"},
                                    ],
                                    "needs_clarification": True,
                                    "question": QUESTION,
                                }
                            ),
                        }
                    }
                ]
            },
        },
    }


def database(row):
    result = Mock()
    result.mappings.return_value.first.return_value = row
    return SimpleNamespace(
        execute=AsyncMock(return_value=result), scalar=AsyncMock(return_value=False)
    )


@pytest.mark.asyncio
async def test_precontract_checkpoint_cannot_smuggle_adopted_instruction():
    from service.shared.harness_refinement import RefinementAttempt

    current = Snapshot(admission=admission())
    db = database(proof())
    saved = continuation().model_copy(
        update={
            "refinement": RefinementAttempt(
                baseline_operation=str(uuid4()),
                proposal_operation=str(uuid4()),
                proposal={"instruction": "Подложный принятый урок", "tools": []},
                probe_step=1,
                baseline_evidence_count=0,
                adopted=True,
            )
        }
    )
    with pytest.raises(HarnessFailure, match="task_contract_missing"):
        await save_admission_checkpoint(
            db,
            {"task_id": uuid4()},
            Exchange(opcode="checkpoint", expected_revision=0, continuation=saved),
            current,
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_saves_only_private_continuation_and_never_fabricates_contract():
    current = Snapshot(admission=admission())
    db = database(proof())
    request = Exchange(opcode="checkpoint", expected_revision=0, continuation=continuation())
    await save_admission_checkpoint(db, {"task_id": uuid4()}, request, current)
    query, params = db.execute.await_args.args
    assert "checkpoint=" not in str(query)
    assert "revision=revision+1" in str(query)
    assert Continuation.model_validate_json(params["continuation"]) == request.continuation


@pytest.mark.asyncio
async def test_unknown_spend_cannot_be_hidden_by_a_question_checkpoint():
    db = database(proof())
    db.scalar.return_value = True
    with pytest.raises(HarnessFailure, match="cost_unknown"):
        await save_admission_checkpoint(
            db,
            {"task_id": uuid4()},
            Exchange(
                opcode="checkpoint",
                expected_revision=0,
                continuation=continuation(),
            ),
            Snapshot(admission=admission()),
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["missing", "provider", "question", "not_pending", "tool"])
async def test_uncommitted_mismatched_or_forged_question_cannot_be_checkpointed(fault):
    row = proof()
    if fault == "missing":
        row = None
    elif fault == "provider":
        row["request"]["provider"] = "routerai"
    elif fault == "tool":
        row["receipt"]["message"]["tool_calls"][0]["function"]["name"] = "ide_write_file"
    else:
        function = row["receipt"]["message"]["tool_calls"][0]["function"]
        parsed = json.loads(function["arguments"])
        parsed["question" if fault == "question" else "needs_clarification"] = (
            "Другой вопрос?" if fault == "question" else False
        )
        function["arguments"] = json.dumps(parsed)
    db = database(row)
    with pytest.raises(HarnessFailure, match="task_contract_invalid"):
        await save_admission_checkpoint(
            db,
            {"task_id": uuid4()},
            Exchange(
                opcode="checkpoint",
                expected_revision=0,
                continuation=continuation(),
            ),
            Snapshot(admission=admission()),
        )
    assert db.execute.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"phase": "model"},
        {"next_step": 0},
        {"provider": None},
        {"agent_name": "general"},
        {"clarification": "FAKE_ANSWER"},
    ],
)
async def test_predispatch_boundary_cannot_be_used_as_general_checkpoint(change):
    db = database(proof())
    saved = continuation().model_copy(update=change)
    with pytest.raises(HarnessFailure, match="task_contract_missing"):
        await save_admission_checkpoint(
            db,
            {"task_id": uuid4()},
            Exchange(
                opcode="checkpoint",
                expected_revision=0,
                continuation=saved,
            ),
            Snapshot(admission=admission()),
        )
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_seal_requires_backend_owned_accepted_answer_and_preserves_active_time():
    current = Snapshot(admission=admission(), continuation=continuation())
    db = database(None)
    row = {"active_job_id": uuid4(), "user_id": uuid4(), "thread_id": uuid4()}
    with pytest.raises(HarnessFailure, match="user_decision_required"):
        await require_answered(db, row, current)
    accepted = {
        "prompt": {"prompt": QUESTION, "choices": []},
        "answer": {"choice_id": None, "text": "hello.py"},
    }
    db = database(accepted)
    result = await require_answered(db, row, current)
    assert json.loads(result)["answer"]["text"] == "hello.py"
    query, params = db.execute.await_args.args
    assert "resume_job_id=:job" in str(query) and "state='accepted'" in str(query)
    assert params["model"] == "test"
    from service.shared.harness_protocol import ContractProposal

    state = _sealed_state(
        current,
        ContractProposal(
            kind="change",
            criteria=[{"criterion_id": "file", "kind": "file", "target": "hello.py"}],
        ),
    )
    assert state.budget.active_ms == 50 and state.contract.goal == current.admission.goal
