"""Explicit owned question replies. Passive reads never allocate or dispatch work."""

import json
import math
import time
from typing import Any
from uuid import UUID, uuid5

from service.infrastructure import workspace_client
from service.services.chat.application.documents.context import (
    document_tools_auto_approved,
    validate_document_context,
)
from service.services.chat.application.ide.agent_context import resolve_ide_target
from service.services.chat.application.ide.runtime import IdeRuntimeService
from service.services.chat.domain.documents.context import document_project_id
from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionAnswer,
    QuestionPrompt,
    QuestionRefusal,
    QuestionScope,
    parse_public_question,
)
from service.services.chat.domain.human_questions.reply import QuestionReplyInput
from service.services.chat.persistence.human_questions.repository import HumanQuestionRepository


class HumanQuestionService:
    def __init__(
        self,
        repository: HumanQuestionRepository,
        runtime: IdeRuntimeService,
        redis: Any,
        *,
        budget: Any = None,
        costs: Any = None,
    ):
        self.repository = repository
        self.runtime = runtime
        self.redis = redis
        self.budget = budget
        self.costs = costs

    @staticmethod
    def _public(result: dict | QuestionRefusal | None) -> dict:
        if isinstance(result, QuestionRefusal):
            raise HumanQuestionError(result.code)
        if result is None:
            raise HumanQuestionError("human_question_not_found")
        return parse_public_question(result)

    async def read(self, scope: QuestionScope, question_id: UUID) -> dict:
        return self._public(await self.repository.read(scope, question_id))

    async def answer(
        self, scope: QuestionScope, question_id: UUID, payload: QuestionReplyInput
    ) -> dict:
        question = await self.read(scope, question_id)
        # Terminal unanswered questions cannot admit work, even after a runtime restore.
        if question["state"] in {"cancelled", "expired"}:
            return question
        selected = payload.ide_context or payload.document_context
        raw = selected.model_dump(mode="json")
        project_id = (
            str(payload.ide_context.repository_id)
            if payload.ide_context is not None
            else document_project_id(str(scope.user_id), str(scope.thread_id), raw["path"])
        )
        if payload.surface != question["surface"] or project_id != question["project_id"]:
            raise HumanQuestionError("human_question_binding_changed")
        answer = QuestionAnswer.parse(
            payload.answer.model_dump(),
            QuestionPrompt.parse({key: question[key] for key in ("prompt", "choices")}),
        ).payload()
        revision = raw["generation" if payload.surface == "ide" else "expected_revision"]
        cost = None
        document = None
        if question["state"] == "pending":
            # Accepted same-intent retries recover the original child even after expiry.
            # Only a genuinely new admission requires fresh live workspace authority.
            if payload.surface == "ide":
                await resolve_ide_target(
                    self.runtime, str(scope.thread_id), str(scope.user_id), raw
                )
            else:
                document = await self._validate_document(scope, raw)
            if self.budget is not None:
                planned = await self.repository.plan_answer(scope, question_id, answer, raw)
                if isinstance(planned, QuestionRefusal):
                    raise HumanQuestionError(planned.code)
                cost = await self._quote(
                    planned,
                    auto_approved=payload.surface == "pdf"
                    and document_tools_auto_approved(document),
                )
        return self._public(
            await self.repository.answer(
                scope,
                question_id,
                intent_id=payload.intent_id,
                answer=answer,
                surface=payload.surface,
                project_id=UUID(project_id),
                revision=revision,
                resume_context=raw,
                **({"cost": cost} if cost is not None else {}),
            )
        )

    async def _document_binding(self, scope: QuestionScope) -> dict:
        status, ref = await workspace_client.read_binding_state(self.redis, str(scope.thread_id))
        if status == "unavailable":
            raise HumanQuestionError("human_question_unavailable")
        if not ref or str(ref.get("user_id")) != str(scope.user_id):
            raise HumanQuestionError("human_question_binding_changed")
        try:
            expires_at = float(ref.get("expires_at") or 0)
            alive = math.isfinite(expires_at) and expires_at > time.time()
        except (ValueError, TypeError):
            alive = False
        if not alive:
            raise HumanQuestionError("human_question_binding_changed")
        return ref

    async def _validate_document(self, scope: QuestionScope, raw: dict) -> dict:
        before = await self._document_binding(scope)
        document = await validate_document_context(
            self.redis, str(scope.thread_id), str(scope.user_id), raw
        )
        after = await self._document_binding(scope)
        if before["workspace_id"] != after["workspace_id"]:
            raise HumanQuestionError("human_question_binding_changed")
        if document is None:
            raise HumanQuestionError("human_question_binding_changed")
        return document

    async def _quote(self, resume, *, auto_approved=False):
        if self.budget is None:
            raise HumanQuestionError("human_question_unavailable")
        try:
            return await self.budget.quote(resume, auto_approved=auto_approved)
        except Exception:
            raise HumanQuestionError("human_question_unavailable") from None

    @staticmethod
    def _cost_view(result):
        if isinstance(result, QuestionRefusal):
            raise HumanQuestionError(result.code)
        return result

    async def read_cost(self, scope: QuestionScope, question_id: UUID):
        return self._cost_view(await self.costs.read(scope, question_id))

    async def decide_cost(
        self, scope: QuestionScope, question_id: UUID, offer_id: UUID, decision: str
    ):
        view = await self.read_cost(scope, question_id)
        if decision == "refresh" and view["offer_id"] == str(uuid5(offer_id, "refresh:v1")):
            return view
        if view["offer_id"] != str(offer_id):
            raise HumanQuestionError("human_question_conflict")
        if decision == "accept" and view["state"] == "expired":
            return view
        replacement = None
        if view["state"] in {"pending", "expired"} and decision in {"accept", "refresh"}:
            question = await self.read(scope, question_id)
            resumed = await self.repository.load_resume(
                scope.user_id, scope.thread_id, UUID(question["resume_job_id"])
            )
            if isinstance(resumed, QuestionRefusal):
                raise HumanQuestionError(resumed.code)
            target = json.loads(resumed.target_json)
            document = None
            if resumed.surface == "ide":
                await resolve_ide_target(
                    self.runtime, str(scope.thread_id), str(scope.user_id), target
                )
            else:
                document = await self._validate_document(scope, target)
            if decision == "refresh":
                replacement = await self._quote(
                    resumed, auto_approved=document_tools_auto_approved(document)
                )
        return self._cost_view(
            await self.costs.decide(scope, question_id, offer_id, decision, replacement=replacement)
        )

    async def cancel(self, scope: QuestionScope, question_id: UUID) -> dict:
        # Accepted means use the existing owned child-job Stop; do not undo an answer.
        return self._public(await self.repository.cancel(scope, question_id))
