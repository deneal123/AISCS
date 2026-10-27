"""Private continuation material. Never a public DTO or a broker payload."""

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError

from service.services.chat.domain.documents.context import DocumentContext, document_project_id
from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionPrompt,
    QuestionScope,
    resume_question_continuation,
)
from service.services.chat.domain.human_questions.cost import COST_KEY, QuestionCost
from service.services.chat.domain.human_questions.reply import IdeQuestionContext

RESUME_CONTEXT_KEY = "_human_question_context_v1"
RESUME_JOB_KEY = "_human_question_resume_job_v1"


def resume_target(
    scope: QuestionScope, surface: str, project_id: UUID, revision: str, raw: Any
) -> dict:
    """Validate the same owned target identity at admission and private recovery."""
    try:
        if surface == "ide":
            selected = IdeQuestionContext.model_validate(raw)
            if selected.repository_id != project_id or selected.generation != revision:
                raise ValueError
            return selected.model_dump(mode="json")
        if surface == "pdf":
            document = DocumentContext.model_validate(raw)
            if document.expected_revision != revision or document_project_id(
                str(scope.user_id), str(scope.thread_id), document.path
            ) != str(project_id):
                raise ValueError
            return document.model_dump(mode="json")
        raise ValueError
    except (ValidationError, ValueError, TypeError):
        raise HumanQuestionError("human_question_binding_changed") from None


@dataclass(frozen=True, slots=True)
class QuestionResume:
    question_id: UUID
    source_job_id: UUID
    resume_job_id: UUID
    surface: str
    model: str
    text: str = field(repr=False)
    target_json: str = field(repr=False)
    messages_json: str = field(repr=False)
    cost: QuestionCost | None = field(default=None, repr=False)
    harness_task_id: UUID | None = field(default=None, repr=False)

    @classmethod
    def plan_answer(
        cls, scope: QuestionScope, question: Any, source: Any, answer: dict, target: dict
    ):
        """Plan bytes for pricing, not an accepted answer or execution authority."""
        if question["state"] != "pending" or not question["alive"]:
            raise HumanQuestionError("human_question_conflict")
        return cls._material(scope, question, source, answer, target)

    @classmethod
    def _material(cls, scope: QuestionScope, question: Any, source: Any, answer: dict, raw: dict):
        if (
            question["user_id"] != scope.user_id
            or question["thread_id"] != scope.thread_id
            or question["source_job_id"] != scope.source_job_id
            or source["status"] != "SUCCESS"
        ):
            raise HumanQuestionError("human_question_unavailable")
        target = resume_target(
            scope, question["surface"], question["project_id"], question["revision"], raw
        )
        resumed = resume_question_continuation(
            question["continuation"], QuestionPrompt.parse(question["prompt"]), answer
        )
        text = source["payload"].get("text")
        if type(text) is not str or not text.strip():
            raise HumanQuestionError("human_question_unavailable")
        return cls(
            question["question_id"],
            scope.source_job_id,
            uuid5(question["question_id"], "gpthub:human-question:resume:v1"),
            question["surface"],
            resumed["model"],
            text,
            json.dumps(target, ensure_ascii=False),
            json.dumps(resumed["messages"], ensure_ascii=False),
            harness_task_id=UUID(source["payload"]["_harness_task_v1"])
            if source["payload"].get("_harness_task_v1")
            else None,
        )

    @classmethod
    def from_owned_rows(cls, scope: QuestionScope, question: Any, child: Any, source: Any):
        """Caller owns the SQL scope; this codec rejects incomplete/foreign material."""
        try:
            question_id = question["question_id"]
            child_id = child["id"]
            payload = child["payload"]
            if (
                question["state"] != "accepted"
                or question["user_id"] != scope.user_id
                or question["thread_id"] != scope.thread_id
                or question["source_job_id"] != scope.source_job_id
                or child["status"] not in {"NEW", "PROCESSING"}
                or source["status"] != "SUCCESS"
                or child_id != question["resume_job_id"]
                or child_id != uuid5(question_id, "gpthub:human-question:resume:v1")
                or payload.get("thread_id") != str(scope.thread_id)
                or payload.get("_human_question_parent_v1")
                != {"question_id": str(question_id), "source_job_id": str(scope.source_job_id)}
            ):
                raise ValueError
            resumed = cls._material(
                scope, question, source, question["answer"], payload.get(RESUME_CONTEXT_KEY)
            )
            if COST_KEY not in payload:
                return resumed
            from dataclasses import replace

            cost = QuestionCost.model_validate(payload[COST_KEY])
            if not cost.matches(resumed):
                raise ValueError
            return replace(resumed, cost=cost)
        except (KeyError, ValueError, TypeError, AttributeError, HumanQuestionError):
            raise HumanQuestionError("human_question_unavailable") from None
