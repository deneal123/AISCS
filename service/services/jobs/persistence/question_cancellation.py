"""Terminalize an owned, never-executed question child without needing a worker."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def cancel_unstarted_question(session: AsyncSession, job_id: UUID, user_id: UUID) -> bool:
    # One row UPDATE serializes with quote acceptance, dispatch and first execution.
    # A question row, not a client-supplied private payload key, proves child identity.
    result = await session.execute(
        text(
            "UPDATE profile.user_launch j SET status='FAILURE',"
            "payload=(j.payload::jsonb-'_human_question_dispatch_after_v1'"
            "-'_human_question_dispatch_claim_v1') || "
            "jsonb_build_object('_cancel_requested_v1',true),updated_at=now() "
            "FROM profile.human_question q WHERE j.id=:job AND j.user_id=:owner "
            "AND j.type='CHAT' AND j.status='NEW' "
            "AND q.resume_job_id=j.id AND q.user_id=j.user_id AND q.state='accepted' "
            "AND j.payload->>'thread_id'=CAST(q.thread_id AS text) "
            "AND j.payload->'_human_question_parent_v1'->>'question_id'="
            "CAST(q.question_id AS text) "
            "AND j.payload->'_human_question_parent_v1'->>'source_job_id'="
            "CAST(q.source_job_id AS text) "
            "AND NOT (j.payload::jsonb ?| ARRAY['_execution_attempt_v1',"
            "'_execution_accounting_v1','_usage_journal_v1','_accepted_turn_v1',"
            "'_prepared_turn_v1','_materialization_plan_v1'])"
        ),
        {"job": job_id, "owner": user_id},
    )
    return result.rowcount == 1
