"""Reconcile committed children until first execution, not merely a broker ACK."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from service.services.chat.domain.human_questions.dispatch import QuestionDispatch
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session


class HumanQuestionDispatchRepository(BaseRepository):
    @connection()
    async def claim_pending(
        self, *, session: AsyncSession | None = None
    ) -> tuple[QuestionDispatch, ...]:
        session = require_session(session)
        claim_id = uuid4()
        result = await session.execute(
            text(
                "WITH candidates AS (SELECT j.id,q.question_id,q.thread_id "
                "FROM profile.human_question q "
                "JOIN profile.user_launch j ON j.id=q.resume_job_id AND j.user_id=q.user_id "
                "JOIN profile.user_launch p ON p.id=q.source_job_id AND p.user_id=q.user_id "
                "JOIN profile.chat_threads t ON t.thread_id=q.thread_id AND t.user_id=q.user_id "
                "WHERE q.state='accepted' AND p.status='SUCCESS' AND p.type='CHAT' "
                "AND p.payload->>'thread_id'=CAST(q.thread_id AS text) "
                "AND j.status='NEW' AND j.type='CHAT' AND j.celery_task_id=CAST(j.id AS text) "
                "AND j.payload->>'thread_id'=CAST(q.thread_id AS text) "
                "AND j.payload->'_human_question_parent_v1'->>'question_id'="
                "CAST(q.question_id AS text) "
                "AND j.payload->'_human_question_parent_v1'->>'source_job_id'="
                "CAST(q.source_job_id AS text) "
                "AND j.payload->>'_human_question_dispatch_v1' IN ('pending','sent') "
                "AND j.payload::jsonb ? '_human_question_context_v1' "
                "AND j.payload->'_human_question_cost_v1'->>'state' IN ('accepted','not_required') "
                "AND NOT (j.payload::jsonb ? '_execution_attempt_v1') "
                "AND COALESCE(j.payload::jsonb->'_cancel_requested_v1','false'::jsonb)"
                "<>'true'::jsonb "
                "AND COALESCE((j.payload->>'_human_question_dispatch_after_v1')::timestamptz,"
                "'-infinity'::timestamptz)<=clock_timestamp() "
                "ORDER BY j.created_at,j.id LIMIT 20 FOR UPDATE OF j SKIP LOCKED) "
                "UPDATE profile.user_launch j SET payload=j.payload::jsonb || jsonb_build_object("
                "'_human_question_dispatch_v1','pending',"
                "'_human_question_dispatch_claim_v1',CAST(:claim AS text),"
                "'_human_question_dispatch_after_v1',clock_timestamp()+interval '60 seconds'),"
                "updated_at=now() FROM candidates c WHERE j.id=c.id "
                "RETURNING j.id,j.user_id,c.question_id,c.thread_id"
            ),
            {"claim": str(claim_id)},
        )
        return tuple(
            QuestionDispatch(
                row["id"], row["user_id"], row["thread_id"], row["question_id"], claim_id
            )
            for row in result.mappings()
        )

    @connection()
    async def acknowledge(
        self, claim: QuestionDispatch, *, session: AsyncSession | None = None
    ) -> bool:
        # Broker acceptance is not proof of worker hydration. Keep the same
        # bounded retry lease until a durable first-attempt/terminal fact exists.
        session = require_session(session)
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload="
                "(payload::jsonb-'_human_question_dispatch_claim_v1') "
                "|| jsonb_build_object('_human_question_dispatch_v1','sent',"
                "'_human_question_dispatch_after_v1',clock_timestamp()+interval '60 seconds'),"
                "updated_at=now() "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' "
                "AND payload->>'thread_id'=:thread "
                "AND payload->>'_human_question_dispatch_v1'='pending' "
                "AND payload->>'_human_question_dispatch_claim_v1'=:claim"
            ),
            {
                "job": claim.job_id,
                "owner": claim.user_id,
                "thread": str(claim.thread_id),
                "claim": str(claim.claim_id),
            },
        )
        return result.rowcount == 1
