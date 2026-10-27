"""Предконтрактная пауза и ACK: локальный HTTP transport, не сквозная приёмка."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.application.agent_execution_service import _finalize_reply
from service.application.harness import admission, clarification
from service.application.reply_assembler import ReplyAssembler
from service.domain.client.protocol import PinSource
from service.domain.execution.context import PrivateRunResources, use_run_execution
from service.infrastructure.harness.client import HarnessClient
from service.shared.harness_protocol import Continuation, ContractProposal, HarnessFailure, Snapshot
from service.shared.human_question import resume_question_continuation
from service.shared.task_contract import TaskContract, TaskState
from tests.test_harness_reconciliation import current

QUESTION = "Как должен называться создаваемый файл?"
PROPOSAL = ContractProposal(
    kind="change",
    criteria=[{"criterion_id": "script", "kind": "file", "target": "hello.py"}],
    needs_clarification=True,
    question=QUESTION,
)


class Journal:
    def __init__(self, *, lose_ack=False):
        self.saved = Snapshot(admission=current().admission)
        self.calls = []
        self.lose_ack = lose_ack

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body["opcode"])
        if body["opcode"] == "checkpoint":
            self.saved = self.saved.model_copy(
                update={
                    "revision": self.saved.revision + 1,
                    "continuation": Continuation.model_validate(body["continuation"]),
                }
            )
            if self.lose_ack:
                self.lose_ack = False
                raise httpx.ReadError("PRIVATE_NETWORK", request=request)
        elif body["opcode"] == "seal":
            accepted = self.saved.admission
            state = TaskState(
                contract=TaskContract(
                    task_id=accepted.task_id,
                    project_id=accepted.project_id,
                    generation=accepted.generation,
                    goal=accepted.goal,
                    kind="change",
                    actions=accepted.actions,
                    credit_limit=accepted.credit_limit,
                    criteria=body["proposal"]["criteria"],
                ),
                source_revision=accepted.source_revision,
            )
            self.saved = self.saved.model_copy(
                update={
                    "state": state,
                    "revision": self.saved.revision + 1,
                    "continuation": Continuation(
                        phase="model",
                        provider=self.saved.continuation.provider,
                        next_step=self.saved.continuation.next_step,
                        clarification=json.dumps(
                            {
                                "question": QUESTION,
                                "answer": {"choice_id": None, "text": "hello.py"},
                            }
                        ),
                    ),
                }
            )
        return httpx.Response(200, json={"snapshot": self.saved.model_dump(mode="json")})

    def client(self):
        client = HarnessClient(
            {"task_id": self.saved.admission.task_id, "capability": "PRIVATE"},
            transport=httpx.MockTransport(self),
        )
        client.current = self.saved
        return client


def attach(execution, journal, *, enabled=True):
    execution.harness = journal.client()
    execution.policy.set_flag("human_questions_enabled", enabled)
    execution.provider_session.pin("gigachat", "test-model", source=PinSource.NON_STREAM_RESPONSE)


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_ack", [False, True])
async def test_pause_has_durable_binding_and_private_terminal_without_tool_effects(lose_ack):
    journal = Journal(lose_ack=lose_ack)
    with use_run_execution(PrivateRunResources()) as execution:
        attach(execution, journal)
        await clarification.park(
            execution, PROPOSAL, [{"role": "user", "content": journal.saved.admission.goal}]
        )
        assert execution.question.waiting and execution.task_state is None
        assert (
            journal.saved.state is None
            and journal.saved.continuation.provider.provider == "gigachat"
        )
        assert journal.saved.continuation.next_step == 1
        assert journal.calls.count("checkpoint") == 1
        assert set(journal.calls) <= {"checkpoint", "state"}
        result = await _finalize_reply(
            reply_assembler=ReplyAssembler(execution.usage),
            metadata={},
            timings=None,
            workspace_ref=None,
            resolved_model="test-model",
        )
        assert result["metadata"]["execution_status"] == "waiting_user"
        assert result["metadata"]["task_result"]["status"] == "waiting_user"
        assert "_human_question_pause_v1" in result
        assert "messages" not in json.dumps(result["metadata"])
        assert "PRIVATE" not in json.dumps(result["metadata"])


@pytest.mark.asyncio
async def test_reload_republishes_same_question_without_another_paid_call(monkeypatch):
    journal = Journal()
    with use_run_execution(PrivateRunResources()) as execution:
        attach(execution, journal)
        await clarification.park(
            execution, PROPOSAL, [{"role": "user", "content": "Исходная задача"}]
        )
    invoke = AsyncMock()
    monkeypatch.setattr(admission, "invoke_model_call", invoke)
    with use_run_execution(PrivateRunResources()) as execution:
        attach(execution, journal)
        await admission.seal_harness(execution, "test-model")
        assert execution.question.waiting and execution.question.prompt.prompt == QUESTION
    invoke.assert_not_awaited()
    assert journal.calls == ["checkpoint"]


@pytest.mark.asyncio
async def test_answer_seals_original_goal_and_survives_restart_before_product_checkpoint(
    monkeypatch,
):
    journal = Journal()
    with use_run_execution(PrivateRunResources()) as execution:
        attach(execution, journal)
        await clarification.park(
            execution, PROPOSAL, [{"role": "user", "content": "Исходная задача"}]
        )
        paused = json.loads(execution.question.continuation_json)
        execution.question.resume_json = json.dumps(
            resume_question_continuation(
                paused,
                execution.question.prompt,
                {"choice_id": None, "text": "hello.py"},
            )
        )
        proposal = PROPOSAL.model_copy(update={"needs_clarification": False, "question": ""})
        invoke = AsyncMock(
            return_value=SimpleNamespace(
                response={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "function": {
                                            "name": "submit_task_contract",
                                            "arguments": proposal.model_dump_json(),
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                }
            )
        )
        monkeypatch.setattr(admission, "invoke_model_call", invoke)
        await admission.seal_harness(execution, "test-model")
        assert execution.task_state.contract.goal == journal.saved.admission.goal
        assert execution.question.resume_json is None
        assert not execution.question.waiting
        assert "hello.py" in clarification.clarified_input(execution, "Исходная задача")
        assert (
            json.loads(invoke.await_args.kwargs["messages"][-1]["content"])["answer"]["text"]
            == "hello.py"
        )
    monkeypatch.setattr(admission, "HarnessClient", lambda _reference: journal.client())
    with use_run_execution(PrivateRunResources(workspace_ref={"harness_ref": {}})) as execution:
        await admission.install_harness(execution)
        assert "hello.py" in clarification.clarified_input(execution, "Исходная задача")
        assert execution.provider_session.pinned_model == "test-model"


@pytest.mark.asyncio
async def test_disabled_questions_never_create_planning_checkpoint():
    journal = Journal()
    with use_run_execution(PrivateRunResources()) as execution:
        attach(execution, journal, enabled=False)
        with pytest.raises(HarnessFailure, match="user_decision_required"):
            await clarification.park(execution, PROPOSAL, [])
    assert journal.calls == []
