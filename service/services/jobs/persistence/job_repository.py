import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from service.models.db.db_models import UserLaunch
from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus
from service.services.jobs.persistence.question_cancellation import cancel_unstarted_question
from service.services.jobs.persistence.transitions import guarded_payload
from service.shared.repositories.base_repository import BaseRepository
from service.shared.repositories.decorators.session_processor import connection, require_session

logger = logging.getLogger(__name__)


class JobRepository(BaseRepository):
    @connection()
    async def cancel_unstarted_question(
        self, job_id: UUID, user_id: UUID, *, session: AsyncSession | None = None
    ) -> bool:
        return await cancel_unstarted_question(require_session(session), job_id, user_id)

    async def stage_execution_accounting(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        attempt_id: str,
        envelope: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """Write validated reservation facts once inside the owned row lock."""
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
                "'{_execution_accounting_v1}',CAST(:envelope AS jsonb),true),updated_at=now() "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' AND status='PROCESSING' "
                "AND payload->>'thread_id'=:thread "
                "AND payload->>'_execution_attempt_v1'=:attempt "
                "AND NOT (payload::jsonb ? '_execution_accounting_v1')"
            ),
            {
                "job": job_id,
                "owner": user_id,
                "thread": thread_id,
                "attempt": attempt_id,
                "envelope": envelope,
            },
        )
        return result.rowcount == 1

    async def stage_usage_journal(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        attempt_id: str,
        envelope: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """Write a validated private journal inside the caller's owned row lock."""
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set(payload::jsonb,"
                "'{_usage_journal_v1}',CAST(:envelope AS jsonb),true),updated_at=now() "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' AND status='PROCESSING' "
                "AND payload->>'thread_id'=:thread "
                "AND payload->>'_execution_attempt_v1'=:attempt "
                "AND NOT (payload::jsonb ? '_accepted_turn_v1') "
                "AND NOT (payload::jsonb ? '_prepared_turn_v1') "
                "AND NOT (payload::jsonb ? '_materialization_plan_v1')"
            ),
            {
                "job": job_id,
                "owner": user_id,
                "thread": thread_id,
                "attempt": attempt_id,
                "envelope": envelope,
            },
        )
        return result.rowcount == 1

    async def claim_chat_execution(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        attempt_id: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """First durable execution admission, without committing caller transaction."""
        attempt_id = str(UUID(attempt_id))
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set("
                "COALESCE(payload::jsonb,'{}'::jsonb),'{_execution_attempt_v1}',"
                "to_jsonb(CAST(:attempt AS text)),true),updated_at=now() "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' "
                "AND status IN ('NEW','PROCESSING') AND payload->>'thread_id'=:thread "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_execution_attempt_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_accepted_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_prepared_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_materialization_plan_v1') "
                "AND COALESCE(payload::jsonb->'_cancel_requested_v1','false'::jsonb) "
                "<>'true'::jsonb"
            ),
            {"job": job_id, "owner": user_id, "thread": thread_id, "attempt": attempt_id},
        )
        return result.rowcount == 1

    @connection()
    async def is_chat_cancel_requested(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        session: AsyncSession | None = None,
    ) -> bool:
        """Read committed owned intent; accepted recovery always wins over cancellation."""
        session = require_session(session)
        result = await session.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM profile.user_launch "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' "
                "AND status IN ('NEW','PROCESSING') "
                "AND payload->>'thread_id'=:thread "
                "AND payload::jsonb->'_cancel_requested_v1'='true'::jsonb "
                "AND NOT (payload::jsonb ? '_accepted_turn_v1') "
                "AND NOT (payload::jsonb ? '_prepared_turn_v1') "
                "AND NOT (payload::jsonb ? '_materialization_plan_v1'))"
            ),
            {"job": job_id, "owner": user_id, "thread": thread_id},
        )
        return result is True

    @connection()
    async def request_chat_cancel(
        self, job_id: UUID, user_id: UUID, session: AsyncSession | None = None
    ) -> bool:
        """Persist a bounded intent without superseding accepted facts or terminal state."""
        session = require_session(session)
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set("
                "COALESCE(payload::jsonb,'{}'::jsonb),'{_cancel_requested_v1}',"
                "'true'::jsonb,true),updated_at=now() "
                "WHERE id=:job AND user_id=:owner AND type='CHAT' "
                "AND status IN ('NEW','PROCESSING') "
                "AND COALESCE(payload::jsonb,'{}'::jsonb) ? 'thread_id' "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_accepted_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_prepared_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_materialization_plan_v1')"
            ),
            {"job": job_id, "owner": user_id},
        )
        return bool(result.rowcount)

    async def stage_accepted_materialization(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        envelope: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """Atomically admit accepted facts and their immutable recovery plan.

        Caller supplies a validated private envelope with exactly two keys.
        A separate plan write would leave a crash window authorizing neither
        safe materialization nor model replay. No commit is owned here.
        """
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload="
                "COALESCE(payload::jsonb,'{}'::jsonb) || CAST(:envelope AS JSONB), "
                "updated_at=now() WHERE id=:job_id AND user_id=:user_id AND status=:status "
                "AND payload->>'thread_id'=:thread_id "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_accepted_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_materialization_plan_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_prepared_turn_v1') "
                "AND (CAST(:envelope AS JSONB) - '_accepted_turn_v1' "
                "- '_materialization_plan_v1')='{}'::jsonb "
                "AND CAST(:envelope AS JSONB) ? '_accepted_turn_v1' "
                "AND CAST(:envelope AS JSONB) ? '_materialization_plan_v1'"
            ),
            {
                "job_id": job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "status": ProcessingStatus.PROCESSING.value,
                "envelope": envelope,
            },
        )
        return bool(result.rowcount)

    async def stage_accepted_turn(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        envelope: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """First-winner receipt/reply latch, before artifact materialization."""
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set("
                "COALESCE(payload::jsonb,'{}'::jsonb),'{_accepted_turn_v1}',"
                "CAST(:envelope AS JSONB),true), updated_at=now() "
                "WHERE id=:job_id AND user_id=:user_id AND status=:status "
                "AND payload->>'thread_id'=:thread_id "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_accepted_turn_v1') "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_prepared_turn_v1')"
            ),
            {
                "job_id": job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "status": ProcessingStatus.PROCESSING.value,
                "envelope": envelope,
            },
        )
        return bool(result.rowcount)

    async def lock_prepared_turn(
        self, job_id: UUID, user_id: UUID, *, session: AsyncSession
    ) -> dict | None:
        """Serialize result settlement in the caller's transaction, without payload logs."""
        result = await session.execute(
            text(
                "SELECT status, payload FROM profile.user_launch "
                "WHERE id=:job AND user_id=:owner FOR UPDATE"
            ),
            {"job": job_id, "owner": user_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def stage_prepared_turn(
        self,
        job_id: UUID,
        user_id: UUID,
        thread_id: str,
        envelope: str,
        *,
        session: AsyncSession,
    ) -> bool:
        """Atomically admit one private prepared result without replacing job payload.

        The predicate is rechecked under PostgreSQL's row lock, so concurrent
        deliveries cannot both replace the same prepared result.
        """
        # Explicit caller ownership avoids the generic repository decorator's
        # raw SQL exception logging: bound result content must never be logged.
        result = await session.execute(
            text(
                "UPDATE profile.user_launch SET payload=jsonb_set("
                "COALESCE(payload::jsonb,'{}'::jsonb),'{_prepared_turn_v1}',"
                "CAST(:envelope AS JSONB),true), updated_at=now() "
                "WHERE id=:job_id AND user_id=:user_id AND status=:status "
                "AND payload->>'thread_id'=:thread_id "
                "AND NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_prepared_turn_v1') "
                "AND (NOT (COALESCE(payload::jsonb,'{}'::jsonb) ? '_accepted_turn_v1') "
                "OR (payload->'_accepted_turn_v1'->'body'->'reply' "
                "= CAST(:envelope AS JSONB)->'body'->'reply' "
                "AND payload->'_accepted_turn_v1'->'body'->'model' "
                "= CAST(:envelope AS JSONB)->'body'->'model' "
                "AND payload->'_accepted_turn_v1'->'body'->'usage' "
                "= CAST(:envelope AS JSONB)->'body'->'usage' "
                "AND payload->'_accepted_turn_v1'->'body'->'job_id' "
                "= CAST(:envelope AS JSONB)->'body'->'job_id' "
                "AND payload->'_accepted_turn_v1'->'body'->'owner_id' "
                "= CAST(:envelope AS JSONB)->'body'->'owner_id' "
                "AND payload->'_accepted_turn_v1'->'body'->'thread_id' "
                "= CAST(:envelope AS JSONB)->'body'->'thread_id'))"
            ),
            {
                "job_id": job_id,
                "user_id": user_id,
                "thread_id": thread_id,
                "status": ProcessingStatus.PROCESSING.value,
                "envelope": envelope,
            },
        )
        return bool(result.rowcount)

    @connection()
    async def create_job(self, job: JobLogic, session: AsyncSession | None = None) -> JobLogic:
        session = require_session(session)
        # A chat job payload contains the user's exact request.  Keep repository
        # diagnostics structural so enabling DEBUG in development or production
        # cannot turn the job queue into a second prompt log.
        logger.debug(
            "Creating job id=%s type=%s status=%s has_payload=%s",
            job.id,
            job.type,
            job.status,
            job.payload is not None,
        )

        new_job = UserLaunch(
            user_id=job.user_id,
            type=job.type,
            status=job.status,
            payload=job.payload,
        )
        session.add(new_job)
        await session.flush()
        return JobLogic.model_validate(new_job)

    @connection()
    async def fetch_job_by_id(
        self, job_id: UUID, user_id: UUID, session: AsyncSession | None = None
    ) -> JobLogic | None:
        session = require_session(session)
        logger.debug(f"Fetching job by id: {job_id} for user: {user_id}")

        stmt = select(UserLaunch).where(UserLaunch.id == job_id, UserLaunch.user_id == user_id)
        result = await session.execute(stmt)

        if db_job := result.scalar_one_or_none():
            return JobLogic.model_validate(db_job)
        return None

    @connection()
    async def fetch_job_by_task_id(
        self, task_id: str, user_id: UUID, session: AsyncSession | None = None
    ) -> JobLogic | None:
        """Authorize task controls through an owned durable launch, including legacy links."""
        session = require_session(session)
        result = await session.execute(
            select(UserLaunch).where(
                UserLaunch.user_id == user_id,
                or_(
                    UserLaunch.celery_task_id == task_id,
                    UserLaunch.payload["celery_task_id"].as_string() == task_id,
                ),
            )
        )
        row = result.scalar_one_or_none()
        return JobLogic.model_validate(row) if row is not None else None

    @connection()
    async def fetch_jobs_by_user_id(
        self,
        user_id: UUID,
        statuses: list[ProcessingStatus],
        session: AsyncSession | None = None,
    ) -> list[JobLogic]:
        session = require_session(session)
        logger.debug(f"Fetching jobs for user: {user_id}")

        stmt = select(UserLaunch).where(
            UserLaunch.user_id == user_id, UserLaunch.status.in_(statuses)
        )
        result = await session.execute(stmt)
        return [JobLogic.model_validate(job) for job in result.scalars().all()]

    @connection()
    async def update_job_status(
        self,
        job: JobLogic,
        session: AsyncSession | None = None,
        *,
        expected_recovery: dict | None = None,
    ) -> JobLogic | None:
        session = require_session(session)
        logger.debug("updating job status", extra={"component": "job_repository"})
        # Lock the owned row before a whole-payload ORM write. Otherwise an old
        # JobLogic can erase a cancellation committed by the control plane.
        # Selecting a scalar avoids stale identity-map objects in long sessions.
        result = await session.execute(
            select(UserLaunch.status, UserLaunch.payload)
            .where(UserLaunch.id == job.id, UserLaunch.user_id == job.user_id)
            .with_for_update()
        )
        stored_status, stored_payload = result.one()
        payload = guarded_payload(
            stored_status, stored_payload, job.status, job.payload, expected_recovery
        )

        updating_job = UserLaunch(
            id=job.id,
            user_id=job.user_id,
            type=job.type,
            status=job.status,
            created_at=job.created_at,
            updated_at=job.updated_at,
            payload=payload,
        )
        await session.merge(updating_job)
        await session.flush()
        return JobLogic.model_validate(updating_job)

    @connection()
    async def fetch_new_jobs(
        self, limit: int = 10, session: AsyncSession | None = None
    ) -> list[JobLogic]:
        session = require_session(session)
        logger.debug(f"Fetching {limit} new jobs")

        # Atomically claim a batch of NEW jobs: lock them with SKIP LOCKED and flip
        # them to PROCESSING in a single round-trip, returning the claimed rows.
        # Replaces the previous select + update + select sequence (3 round-trips and
        # a race window between claiming and re-reading).
        locked_ids = (
            select(UserLaunch.id)
            .where(UserLaunch.status == ProcessingStatus.NEW, UserLaunch.type == ServiceType.CHAT)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        stmt = (
            update(UserLaunch)
            .where(UserLaunch.id.in_(locked_ids))
            .values(status=ProcessingStatus.PROCESSING)
            .returning(UserLaunch)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(stmt)
        jobs = [JobLogic.model_validate(job) for job in result.scalars().all()]
        logger.debug(f"Fetched: {len(jobs)} jobs")
        return jobs

    @connection()
    async def fetch_stale_processing_jobs(
        self,
        stale_threshold_sec: int = 3600,
        limit: int = 100,
        session: AsyncSession | None = None,
    ) -> list[JobLogic]:
        session = require_session(session)
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_threshold_sec)
        logger.debug(f"Fetching stale PROCESSING jobs older than {cutoff}")

        stmt = (
            select(UserLaunch)
            .where(
                UserLaunch.status == ProcessingStatus.PROCESSING,
                UserLaunch.updated_at < cutoff,
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        jobs = [JobLogic.model_validate(job) for job in result.scalars().all()]
        logger.debug(f"Found {len(jobs)} stale PROCESSING jobs")
        return jobs

    @connection()
    async def delete_old_completed_jobs(
        self,
        retention_days: int = 30,
        limit: int = 500,
        session: AsyncSession | None = None,
    ) -> int:
        session = require_session(session)
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        logger.debug(f"Deleting completed/failed jobs older than {cutoff}")

        stmt = (
            select(UserLaunch.id)
            .where(
                UserLaunch.status.in_([ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE]),
                UserLaunch.updated_at < cutoff,
            )
            .limit(limit)
        )
        result = await session.execute(stmt)
        job_ids = [row[0] for row in result.fetchall()]

        if not job_ids:
            logger.debug("No old jobs to delete")
            return 0

        await session.execute(delete(UserLaunch).where(UserLaunch.id.in_(job_ids)))
        await session.flush()

        logger.info(f"Deleted {len(job_ids)} old jobs")
        return len(job_ids)

    @connection()
    async def update_job_celery_task_id(
        self, job_id: UUID, celery_task_id: str, session: AsyncSession | None = None
    ) -> None:
        session = require_session(session)
        logger.debug(f"Updating job celery_task_id: {job_id}")

        stmt = (
            update(UserLaunch).where(UserLaunch.id == job_id).values(celery_task_id=celery_task_id)
        )
        await session.execute(stmt)
        await session.flush()
