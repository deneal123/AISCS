"""Долговечная предконтрактная пауза; ни критериев выполнения, ни прав на эффекты."""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionAnswer,
    QuestionPrompt,
    freeze_question_continuation,
)
from service.services.chat.persistence.harness.reservations import require_reconciled_cost
from service.shared.harness_protocol import ContractProposal, Exchange, HarnessFailure, Snapshot


async def save_admission_checkpoint(
    db: AsyncSession, row: Mapping[str, Any], request: Exchange, current: Snapshot
) -> None:
    saved = request.continuation
    if (
        saved is None
        or request.state is not None
        or saved.refinement is not None
        or saved.clarification is not None
        or current.continuation.messages
        or saved.phase != "admitting"
        or saved.provider is None
        or saved.agent_name is not None
        or saved.next_step != current.continuation.next_step + 1
        or not current.continuation.admission_active_ms
        <= saved.admission_active_ms
        <= current.admission.active_limit_ms
    ):
        raise HarnessFailure("task_contract_missing")
    await require_reconciled_cost(db, row["task_id"])
    receipt = (
        (
            await db.execute(
                text(
                    "SELECT request,receipt FROM profile.harness_grant WHERE task_id=:task "
                    "AND state='succeeded' AND request->>'kind'='meta_usage' "
                    "ORDER BY created_at DESC,operation_id DESC LIMIT 1"
                ),
                {"task": row["task_id"]},
            )
        )
        .mappings()
        .first()
    )
    if receipt is None:
        raise HarnessFailure("task_contract_invalid")
    try:
        call = receipt["request"]
        message = receipt["receipt"]["message"]
        tool_calls = message["tool_calls"]
        if len(tool_calls) != 1:
            raise ValueError
        function = tool_calls[0]["function"]
        if function["name"] != "submit_task_contract":
            raise ValueError
        proposal = ContractProposal.model_validate(json.loads(function["arguments"]))
        if (
            not proposal.needs_clarification
            or not proposal.question
            or (call["provider"], call["model"]) != (saved.provider.provider, saved.provider.model)
        ):
            raise ValueError
        prompt = QuestionPrompt.parse({"prompt": proposal.question, "choices": []})
        messages = saved.conversation()
        freeze_question_continuation(
            {
                "model": saved.provider.model,
                "messages": messages,
                "tool_call_id": messages[-1]["tool_call_id"],
            },
            prompt,
        )
    except (HumanQuestionError, ValueError, KeyError, TypeError, IndexError):
        raise HarnessFailure("task_contract_invalid") from None
    await db.execute(
        text(
            "UPDATE profile.harness_task SET continuation=CAST(:continuation AS jsonb),"
            "revision=revision+1,updated_at=now() WHERE task_id=:task"
        ),
        {"task": row["task_id"], "continuation": saved.model_dump_json()},
    )


async def require_answered(
    db: AsyncSession, row: Mapping[str, Any], current: Snapshot
) -> str | None:
    if not current.continuation.messages:
        return None
    if current.continuation.provider is None:
        raise HarnessFailure("provider_state_incompatible")
    accepted = (
        (
            await db.execute(
                text(
                    "SELECT prompt,answer FROM profile.human_question WHERE resume_job_id=:job "
                    "AND user_id=:user AND thread_id=:thread AND state='accepted' "
                    "AND continuation->>'model'=:model "
                    "AND continuation->'messages'=CAST(:messages AS jsonb)"
                ),
                {
                    "job": row["active_job_id"],
                    "user": row["user_id"],
                    "thread": row["thread_id"],
                    "messages": json.dumps(current.continuation.conversation()),
                    "model": current.continuation.provider.model,
                },
            )
        )
        .mappings()
        .first()
    )
    if accepted is None:
        raise HarnessFailure("user_decision_required")
    prompt = QuestionPrompt.parse(accepted["prompt"])
    answer = QuestionAnswer.parse(accepted["answer"], prompt)
    return json.dumps({"question": prompt.prompt, "answer": answer.payload()}, ensure_ascii=False)
