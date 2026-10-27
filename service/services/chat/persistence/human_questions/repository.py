"""Owned question journal. No broker, model or workspace I/O inside transactions.

Not a public admission API: the application must revalidate the selected live
project binding before accepting an answer and dispatch the durable child intent.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.human_questions.contracts import (
    HumanQuestionError,
    QuestionAnswer,
    QuestionPause,
    QuestionPrompt,
    QuestionRefusal,
    QuestionScope,
)
from service.services.chat.domain.human_questions.cost import COST_KEY, QuestionCost
from service.services.chat.domain.human_questions.resume import (
    RESUME_CONTEXT_KEY,
    QuestionResume,
    resume_target,
)
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

_OWNER = (
    "FROM profile.user_launch j JOIN profile.chat_threads t "
    "ON t.thread_id=:thread_id AND t.user_id=:user_id "
    "WHERE j.id=:source_job_id AND j.user_id=:user_id AND j.type='CHAT' "
    "AND j.payload->>'thread_id'=CAST(:thread_id AS text)"
)


async def _owner(session: AsyncSession, scope: QuestionScope) -> Any:
    return (
        (
            await session.execute(
                text(f"SELECT j.status,j.payload {_OWNER} FOR UPDATE OF j FOR SHARE OF t"),
                scope.params(),
            )
        )
        .mappings()
        .first()
    )


async def _read(
    session: AsyncSession, scope: QuestionScope, question_id: UUID, *, lock: bool = False
) -> Any:
    return (
        (
            await session.execute(
                text(
                    "SELECT q.*,q.expires_at>clock_timestamp() AS alive "
                    "FROM profile.human_question q WHERE q.question_id=:question_id "
                    "AND q.source_job_id=:source_job_id AND q.thread_id=:thread_id "
                    "AND q.user_id=:user_id "
                    f"AND EXISTS(SELECT 1 {_OWNER})" + (" FOR UPDATE OF q" if lock else "")
                ),
                {**scope.params(), "question_id": question_id},
            )
        )
        .mappings()
        .first()
    )


def public_question(row: Any) -> dict[str, Any]:
    """Explicit whitelist: no transcript, answer, credentials or execution capability."""
    prompt = QuestionPrompt.parse(row["prompt"])
    return {
        "question_id": str(row["question_id"]),
        "source_job_id": str(row["source_job_id"]),
        "surface": row["surface"],
        "project_id": str(row["project_id"]),
        **prompt.payload(),
        "state": "expired" if row["state"] == "pending" and not row["alive"] else row["state"],
        "expires_at": row["expires_at"].isoformat(),
        "resume_job_id": str(row["resume_job_id"]) if row["resume_job_id"] else None,
    }


class HumanQuestionRepository(BaseRepository):
    @connection()
    async def plan_answer(
        self,
        scope: QuestionScope,
        question_id: UUID,
        answer: dict,
        target: dict,
        *,
        session: AsyncSession | None = None,
    ):
        session = require_session(session)
        source = await _owner(session, scope)
        row = await _read(session, scope, question_id) if source is not None else None
        if row is None:
            return QuestionRefusal("human_question_not_found")
        try:
            return QuestionResume.plan_answer(scope, row, source, answer, target)
        except HumanQuestionError as error:
            return QuestionRefusal(error.code)

    async def stage(
        self, pause: QuestionPause, *, session: AsyncSession
    ) -> dict[str, Any] | QuestionRefusal:
        """Caller must commit with accepted/materialization facts; never commit alone.

        Explicit caller session prevents accidentally persisting a question in a
        standalone decorator transaction. The terminal original job owns visibility.
        """
        session = require_session(session)
        owner = await _owner(session, pause.scope)
        if owner is None:
            return QuestionRefusal("human_question_not_found")
        params = pause.params()
        previous = await _read(session, pause.scope, pause.question_id, lock=True)
        if previous is not None:
            if (
                previous["digest"] != params["digest"]
                or previous["execution_attempt_id"] != pause.execution_attempt_id
            ):
                return QuestionRefusal("human_question_conflict")
            return public_question(previous)
        payload = owner["payload"] or {}
        if (
            owner["status"] != "PROCESSING"
            or payload.get("_execution_attempt_v1") != str(pause.execution_attempt_id)
            or payload.get("_cancel_requested_v1") is True
        ):
            return QuestionRefusal("human_question_unavailable")
        result = await session.execute(
            text(
                "INSERT INTO profile.human_question "
                "(question_id,source_job_id,thread_id,user_id,execution_attempt_id,surface,project_id,"
                "revision,prompt,continuation,digest,expires_at,state) "
                "SELECT :question_id,:source_job_id,:thread_id,:user_id,CAST(:attempt_id AS uuid),"
                ":surface,:project_id,:revision,CAST(:prompt AS jsonb),"
                "CAST(:continuation AS jsonb),:digest,to_timestamp(:expires_at),"
                "CASE WHEN to_timestamp(:expires_at)>clock_timestamp() "
                "THEN 'pending' ELSE 'expired' END "
                "ON CONFLICT DO NOTHING RETURNING question_id"
            ),
            params,
        )
        if result.scalar() is None:
            return QuestionRefusal("human_question_conflict")
        return public_question(await _read(session, pause.scope, pause.question_id))

    @connection()
    async def read_staged(
        self, scope: QuestionScope, question_id: UUID, *, session: AsyncSession | None = None
    ) -> dict[str, Any] | None:
        """Worker recovery only; no private continuation and no public read admission."""
        row = await _read(require_session(session), scope, question_id)
        return public_question(row) if row is not None else None

    @connection()
    async def read(
        self, scope: QuestionScope, question_id: UUID, *, session: AsyncSession | None = None
    ) -> dict[str, Any] | None:
        session = require_session(session)
        owner = await _owner(session, scope)
        if owner is None or owner["status"] != "SUCCESS":
            return None
        row = await _read(session, scope, question_id)
        return public_question(row) if row is not None else None

    @connection()
    async def answer(
        self,
        scope: QuestionScope,
        question_id: UUID,
        *,
        intent_id: UUID,
        answer: dict[str, Any],
        surface: str,
        project_id: UUID,
        revision: str,
        resume_context: dict | None = None,
        cost: QuestionCost | None = None,
        session: AsyncSession | None = None,
    ) -> dict[str, Any] | QuestionRefusal:
        """One answer admits one stable child job, never a second user message/charge.

        The child carries an outbox intent only; no broker call occurs here. Resume
        dispatch/execution still require application integration and fresh authority.
        """
        session = require_session(session)
        owner = await _owner(session, scope)
        if owner is None:
            return QuestionRefusal("human_question_not_found")
        row = await _read(session, scope, question_id, lock=True)
        if row is None:
            return QuestionRefusal("human_question_not_found")
        if (
            owner["status"] != "SUCCESS"
            or row["surface"] != surface
            or row["project_id"] != project_id
            or row["revision"] != revision
        ):
            return QuestionRefusal("human_question_binding_changed")
        if not isinstance(intent_id, UUID) or not intent_id.int:
            return QuestionRefusal("human_question_invalid")
        try:
            parsed = QuestionAnswer.parse(answer, QuestionPrompt.parse(row["prompt"])).payload()
        except HumanQuestionError:
            return QuestionRefusal("human_question_invalid")
        if row["state"] == "accepted":
            if row["answer_intent_id"] != intent_id or row["answer"] != parsed:
                return QuestionRefusal("human_question_conflict")
            return public_question(row)
        if row["state"] != "pending":
            return public_question(row)
        if not row["alive"]:
            await session.execute(
                text(
                    "UPDATE profile.human_question SET state='expired' "
                    "WHERE question_id=:question_id"
                ),
                {"question_id": question_id},
            )
            return public_question({**row, "state": "expired"})
        # Legacy accepted rows remain readable but cannot silently acquire a new
        # continuation target on retry. New application admissions supply this.
        try:
            target = (
                None
                if resume_context is None
                else resume_target(scope, surface, project_id, revision, resume_context)
            )
        except HumanQuestionError:
            return QuestionRefusal("human_question_binding_changed")
        original_text = owner["payload"].get("text")
        if target is not None and (type(original_text) is not str or not original_text.strip()):
            return QuestionRefusal("human_question_unavailable")
        if cost is not None:
            if target is None:
                return QuestionRefusal("human_question_binding_changed")
            planned = QuestionResume.plan_answer(scope, row, owner, parsed, target)
            if cost.state not in {"pending", "not_required"} or not cost.matches(planned):
                return QuestionRefusal("human_question_conflict")
        resume_job_id = uuid5(question_id, "gpthub:human-question:resume:v1")
        changed = await session.execute(
            text(
                "UPDATE profile.human_question SET state='accepted',answer_intent_id=:intent_id,"
                "answer=CAST(:answer AS jsonb),resume_job_id=:resume_job_id,"
                "answered_at=clock_timestamp() WHERE question_id=:question_id "
                "AND state='pending' AND expires_at>clock_timestamp() RETURNING question_id"
            ),
            {
                "question_id": question_id,
                "intent_id": intent_id,
                "answer": json.dumps(parsed, ensure_ascii=False),
                "resume_job_id": resume_job_id,
            },
        )
        if changed.scalar() is None:
            await session.execute(
                text(
                    "UPDATE profile.human_question SET state='expired' "
                    "WHERE question_id=:question_id AND state='pending'"
                ),
                {"question_id": question_id},
            )
            return public_question(await _read(session, scope, question_id))
        payload = {
            "thread_id": str(scope.thread_id),
            "_human_question_parent_v1": {
                "question_id": str(question_id),
                "source_job_id": str(scope.source_job_id),
            },
            "_human_question_dispatch_v1": "pending",
            **({RESUME_CONTEXT_KEY: target, "text": original_text} if target is not None else {}),
            **({COST_KEY: cost.model_dump(mode="json")} if cost is not None else {}),
        }
        await session.execute(
            text(
                "INSERT INTO profile.user_launch "
                "(id,user_id,type,status,payload,celery_task_id,created_at,updated_at) "
                "VALUES (:resume_job_id,:user_id,'CHAT','NEW',CAST(:payload AS jsonb),"
                ":celery_task_id,now(),now())"
            ),
            {
                "resume_job_id": resume_job_id,
                "celery_task_id": str(resume_job_id),
                "user_id": scope.user_id,
                "payload": json.dumps(payload),
            },
        )
        return public_question(await _read(session, scope, question_id))

    @connection()
    async def load_resume(
        self,
        user_id: UUID,
        thread_id: UUID,
        resume_job_id: UUID,
        *,
        session: AsyncSession | None = None,
    ) -> QuestionResume | QuestionRefusal:
        """Worker-only lookup; no public projection, allocation, queue or model I/O."""
        session = require_session(session)
        child = (
            (
                await session.execute(
                    text(
                        "SELECT j.id,j.status,j.payload FROM profile.user_launch j "
                        "JOIN profile.chat_threads t ON t.thread_id=:thread_id "
                        "AND t.user_id=:user_id "
                        "WHERE j.id=:resume_job_id AND j.user_id=:user_id AND j.type='CHAT' "
                        "AND j.payload->>'thread_id'=CAST(:thread_id AS text)"
                    ),
                    {"user_id": user_id, "thread_id": thread_id, "resume_job_id": resume_job_id},
                )
            )
            .mappings()
            .first()
        )
        if child is None:
            return QuestionRefusal("human_question_not_found")
        try:
            parent = child["payload"]["_human_question_parent_v1"]
            if type(parent) is not dict or set(parent) != {"question_id", "source_job_id"}:
                raise ValueError
            scope = QuestionScope(user_id, thread_id, UUID(parent["source_job_id"]))
            question_id = UUID(parent["question_id"])
        except (KeyError, TypeError, ValueError, HumanQuestionError):
            return QuestionRefusal("human_question_unavailable")
        source = await _owner(session, scope)
        question = await _read(session, scope, question_id) if source is not None else None
        if source is None or question is None:
            return QuestionRefusal("human_question_not_found")
        try:
            return QuestionResume.from_owned_rows(scope, question, child, source)
        except HumanQuestionError:
            return QuestionRefusal("human_question_unavailable")

    @connection()
    async def cancel(
        self, scope: QuestionScope, question_id: UUID, *, session: AsyncSession | None = None
    ) -> dict[str, Any] | QuestionRefusal:
        session = require_session(session)
        owner = await _owner(session, scope)
        row = await _read(session, scope, question_id, lock=True) if owner is not None else None
        if row is None or owner["status"] != "SUCCESS":
            return QuestionRefusal("human_question_not_found")
        if row["state"] == "pending":
            await session.execute(
                text(
                    "UPDATE profile.human_question SET state=CASE "
                    "WHEN expires_at>clock_timestamp() "
                    "THEN 'cancelled' ELSE 'expired' END WHERE question_id=:question_id"
                ),
                {"question_id": question_id},
            )
        # Accepted replies own a child job: stopping it is the normal owned Stop,
        # never rewriting the question or accepted model facts here.
        return public_question(await _read(session, scope, question_id))
