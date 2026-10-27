"""Предконтрактный вопрос: только пауза, без полномочий менять проект."""

import json
import time
from typing import Any
from uuid import UUID, uuid5

from service.domain.execution.context import RunExecutionContext
from service.shared.harness_protocol import Continuation, ContractProposal, HarnessFailure
from service.shared.human_question import (
    HumanQuestionError,
    QuestionAnswer,
    QuestionPrompt,
    freeze_question_continuation,
)


def pending(execution: RunExecutionContext) -> bool:
    client = execution.harness
    return (
        client is not None
        and client.current.state is None
        and bool(client.current.continuation.messages)
    )


def restore_question(execution: RunExecutionContext) -> None:
    if not execution.policy.flag("human_questions_enabled"):
        raise HarnessFailure("user_decision_required")
    saved = execution.harness.current.continuation
    messages = saved.conversation()
    prompt = QuestionPrompt.parse(
        json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"])
    )
    execution.question.prompt = prompt
    execution.question.continuation_json = freeze_question_continuation(
        {
            "model": saved.provider.model,
            "messages": messages,
            "tool_call_id": messages[-1]["tool_call_id"],
        },
        prompt,
    )


def answered_messages(execution: RunExecutionContext) -> list[dict[str, Any]] | None:
    """Ответ принимается только из проверенного приватного human-question frame."""
    if not pending(execution) or execution.question.resume_json is None:
        return None
    saved = execution.harness.current.continuation
    resumed = json.loads(execution.question.resume_json)
    if resumed["model"] != saved.provider.model:
        raise HarnessFailure("provider_state_incompatible")
    expected = saved.conversation()
    received = resumed["messages"]
    if (
        received[:-1] != expected[:-1]
        or received[-1]["tool_call_id"] != expected[-1]["tool_call_id"]
    ):
        raise HarnessFailure("operation_conflict")
    return received


async def park(
    execution: RunExecutionContext, proposal: ContractProposal, messages: list[dict[str, Any]]
) -> None:
    if not execution.policy.flag("human_questions_enabled") or not proposal.question.strip():
        raise HarnessFailure("user_decision_required")
    client = execution.harness
    if client.current.continuation.messages:
        raise HarnessFailure("user_decision_required")
    prompt = QuestionPrompt.parse({"prompt": proposal.question, "choices": []})
    binding = execution.provider_session
    if not binding.pinned_provider or not binding.pinned_model:
        raise HarnessFailure("provider_state_incompatible")
    call_id = str(uuid5(UUID(client.task_id), "contract-clarification"))
    conversation = [
        *messages,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "ask_user_question",
                        "arguments": json.dumps(prompt.payload(), ensure_ascii=False),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": '{"awaiting_user":true}'},
    ]
    measured_at = time.monotonic()
    current = client.current
    continuation = Continuation(
        call_payload_version=2,
        messages=conversation,
        phase="admitting",
        next_step=current.continuation.next_step + 1,
        length_continuations=current.continuation.length_continuations,
        admission_active_ms=current.continuation.admission_active_ms
        + int((measured_at - client._active_checkpoint) * 1000),
        provider={
            "provider": binding.pinned_provider,
            "model": binding.pinned_model,
            "state_id": binding.private_state(binding.pinned_provider),
        },
    )
    await client.exchange(
        opcode="checkpoint", expected_revision=current.revision, continuation=continuation
    )
    client._active_checkpoint = measured_at
    restore_question(execution)


def consume_answer(execution: RunExecutionContext, messages: list[dict[str, Any]]) -> None:
    prompt = json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"])["prompt"]
    answer = json.loads(messages[-1]["content"])["answer"]
    expected = {"question": prompt, "answer": answer}
    saved = execution.harness.current.continuation.clarification
    if saved is None or json.loads(saved) != expected:
        raise HarnessFailure("operation_conflict")
    execution.policy.values["harness_clarification"] = expected
    execution.question.resume_json = None
    execution.question.prompt = None
    execution.question.continuation_json = None


def restore_answer(execution: RunExecutionContext, raw: str) -> None:
    try:
        value = json.loads(raw)
        if set(value) != {"question", "answer"}:
            raise ValueError
        prompt = QuestionPrompt.parse({"prompt": value["question"], "choices": []})
        QuestionAnswer.parse(value["answer"], prompt)
    except (HumanQuestionError, ValueError, TypeError, KeyError):
        raise HarnessFailure("task_contract_invalid") from None
    execution.policy.values["harness_clarification"] = value


def clarified_input(execution: RunExecutionContext, text: str) -> str:
    clarification = execution.policy.values.get("harness_clarification")
    if clarification is None:
        return text
    return (
        text + "\nУточнение задачи пользователем:\n" + json.dumps(clarification, ensure_ascii=False)
    )
