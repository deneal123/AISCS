"""Owned same-child cost decisions, serialized with cancellation/first execution."""

import json
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionRefusal,
    QuestionScope,
)
from service.services.chat.domain.human_questions.cost import COST_KEY, QuestionCost
from service.services.chat.domain.human_questions.resume import QuestionResume
from service.services.chat.persistence.human_questions.repository import _owner, _read
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session


async def _owned(session, scope, question_id):
    # Same source → question → child order as answer admission. No model/queue I/O.
    source = await _owner(session, scope)
    question = await _read(session, scope, question_id, lock=True) if source is not None else None
    if (
        source is None
        or source["status"] != "SUCCESS"
        or question is None
        or question["state"] != "accepted"
    ):
        raise HumanQuestionError("human_question_not_found")
    child = (
        (
            await session.execute(
                text(
                    "SELECT id,status,payload,extract(epoch from clock_timestamp()) AS now "
                    "FROM profile.user_launch WHERE id=:child AND user_id=:owner AND type='CHAT' "
                    "AND payload->>'thread_id'=:thread FOR UPDATE"
                ),
                {
                    "child": uuid5(question_id, "gpthub:human-question:resume:v1"),
                    "owner": scope.user_id,
                    "thread": str(scope.thread_id),
                },
            )
        )
        .mappings()
        .first()
    )
    if child is None or child["id"] != question["resume_job_id"]:
        raise HumanQuestionError("human_question_not_found")
    try:
        cost = QuestionCost.model_validate(child["payload"][COST_KEY])
    except (KeyError, ValueError, TypeError):
        raise HumanQuestionError("human_question_unavailable") from None
    return source, question, child, cost


class HumanQuestionCostRepository(BaseRepository):
    @connection()
    async def read(
        self, scope: QuestionScope, question_id: UUID, *, session: AsyncSession | None = None
    ):
        try:
            _, _, child, cost = await _owned(require_session(session), scope, question_id)
            view = cost.public(now=float(child["now"]))
            if (
                cost.state != "declined"
                and child["payload"].get("_cancel_requested_v1") is True
                and not any(
                    key in child["payload"]
                    for key in (
                        "_execution_attempt_v1",
                        "_execution_accounting_v1",
                        "_usage_journal_v1",
                        "_accepted_turn_v1",
                        "_prepared_turn_v1",
                        "_materialization_plan_v1",
                    )
                )
            ):
                view["state"] = "cancelled"
            return view
        except HumanQuestionError as error:
            return QuestionRefusal(error.code)

    @connection()
    async def decide(
        self,
        scope: QuestionScope,
        question_id: UUID,
        offer_id: UUID,
        decision: str,
        *,
        replacement: QuestionCost | None = None,
        session: AsyncSession | None = None,
    ):
        try:
            return await self._decide(
                scope,
                question_id,
                offer_id,
                decision,
                replacement=replacement,
                session=require_session(session),
            )
        except HumanQuestionError as error:
            return QuestionRefusal(error.code)

    async def _decide(self, scope, question_id, offer_id, decision, *, replacement, session):
        session = require_session(session)
        source, question, child, cost = await _owned(session, scope, question_id)
        if decision not in {"accept", "decline", "refresh"}:
            raise HumanQuestionError("human_question_invalid")
        # Refresh retries recover their first replacement, not another quote.
        if decision == "refresh" and cost.offer_id == uuid5(offer_id, "refresh:v1"):
            return cost.public(now=float(child["now"]))
        if cost.offer_id != offer_id:
            raise HumanQuestionError("human_question_conflict")
        expected = {"accept": "accepted", "decline": "declined"}.get(decision)
        if cost.state == expected:
            return cost.public(now=float(child["now"]))
        if (
            cost.state != "pending"
            or child["status"] != "NEW"
            or child["payload"].get("_execution_attempt_v1")
            or child["payload"].get("_cancel_requested_v1") is True
        ):
            raise HumanQuestionError("human_question_conflict")
        resumed = QuestionResume.from_owned_rows(scope, question, child, source)
        if not cost.matches(resumed):
            raise HumanQuestionError("human_question_conflict")
        if decision == "refresh":
            if (
                cost.expires_at > float(child["now"])
                or replacement is None
                or not replacement.matches(resumed)
            ):
                raise HumanQuestionError("human_question_conflict")
            if replacement.state not in {"pending", "not_required"}:
                raise HumanQuestionError("human_question_invalid")
            updated = replacement.model_copy(update={"offer_id": uuid5(offer_id, "refresh:v1")})
        elif decision == "accept" and cost.expires_at <= float(child["now"]):
            return cost.public(now=float(child["now"]))
        else:
            updated = cost.model_copy(update={"state": expected, "decided_at": float(child["now"])})
        delta = {COST_KEY: updated.model_dump(mode="json")}
        if updated.state == "declined":
            delta["_cancel_requested_v1"] = True
        await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=(payload::jsonb-"
                "'_human_question_dispatch_after_v1'-'_human_question_dispatch_claim_v1') "
                "|| CAST(:delta AS jsonb),status=:status,updated_at=now() "
                "WHERE id=:id AND user_id=:owner"
            ),
            {
                "delta": json.dumps(delta),
                "status": "FAILURE" if updated.state == "declined" else "NEW",
                "id": child["id"],
                "owner": scope.user_id,
            },
        )
        return updated.public(now=float(child["now"]))
