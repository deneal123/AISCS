"""Ограниченная повторная доставка в существующем журнале задания, без новых эффектов."""

import json
from uuid import UUID

from sqlalchemy import text

from service.services.chat.persistence.harness.result import read_result
from service.services.chat.persistence.harness.state import snapshot
from service.services.jobs.persistence.transitions import HARNESS_RETRY_KEY
from service.shared.harness_protocol import HarnessFailure
from service.shared.repositories.base_repository import BaseRepository

RETRY_KEY = HARNESS_RETRY_KEY
MAX_RETRIES = 3


def next_retry(previous, attempt_id):
    try:
        return _next_retry(previous, attempt_id)
    except (ValueError, TypeError, AttributeError):
        raise HarnessFailure("checkpoint_conflict") from None


def _next_retry(previous, attempt_id):
    if previous is not None:
        if (
            not isinstance(previous, dict)
            or set(previous) != {"attempt_id", "count", "state"}
            or type(previous["count"]) is not int
            or not 1 <= previous["count"] <= MAX_RETRIES
            or previous["state"] not in {"pending", "blocked"}
            or str(UUID(previous["attempt_id"])) != previous["attempt_id"]
        ):
            raise HarnessFailure("checkpoint_conflict")
        if previous["attempt_id"] == attempt_id or previous["state"] == "blocked":
            return previous
    count = previous["count"] if previous else 0
    return {
        "attempt_id": str(UUID(attempt_id)),
        "count": min(count + 1, MAX_RETRIES),
        "state": "pending" if count < MAX_RETRIES else "blocked",
    }


class HarnessRetryRepository(BaseRepository):
    async def prepare(self, *, task_id, job_id, user_id, thread_id, attempt_id, epoch):
        try:
            async with self.connector.get_session_context() as db:
                row = (
                    (
                        await db.execute(
                            text(
                                "SELECT t.*,j.payload AS job_payload "
                                "FROM profile.harness_task t "
                                "JOIN profile.user_launch j ON j.id=t.active_job_id "
                                "JOIN profile.chat_threads c ON c.thread_id=t.thread_id "
                                "AND c.user_id=t.user_id "
                                "WHERE t.task_id=:task AND t.active_job_id=:job "
                                "AND t.user_id=:owner AND t.thread_id=:thread "
                                "AND t.execution_attempt_id=:attempt AND t.fencing_epoch=:epoch "
                                "AND j.user_id=t.user_id AND j.type='CHAT' "
                                "AND j.status='PROCESSING' "
                                "AND j.payload->>'thread_id'=CAST(CAST(:thread AS uuid) AS text) "
                                "AND j.payload->>'_execution_attempt_v1'="
                                "CAST(CAST(:attempt AS uuid) AS text) "
                                "AND COALESCE(j.payload->>'_cancel_requested_v1','false')<>'true' "
                                "AND NOT (j.payload::jsonb ?| ARRAY['_accepted_turn_v1',"
                                "'_prepared_turn_v1','_materialization_plan_v1']) "
                                "AND t.admission IS NOT NULL FOR UPDATE OF t,j FOR SHARE OF c"
                            ),
                            {
                                "task": UUID(task_id),
                                "job": UUID(job_id),
                                "owner": UUID(user_id),
                                "thread": UUID(thread_id),
                                "attempt": UUID(attempt_id),
                                "epoch": epoch,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise HarnessFailure("harness_fenced")
                decision = next_retry(row["job_payload"].get(RETRY_KEY), attempt_id)
                payload = {**row["job_payload"], RETRY_KEY: decision}
                await db.execute(
                    text(
                        "UPDATE profile.user_launch SET payload=CAST(:body AS jsonb),"
                        "updated_at=now() WHERE id=:job"
                    ),
                    {"job": UUID(job_id), "body": json.dumps(payload)},
                )
                result = None
                if decision["state"] == "blocked":
                    row = {**row, "job_payload": payload}
                    result = await read_result(db, row, await snapshot(db, row))
                await db.commit()
                return decision, result
        except HarnessFailure:
            raise
        except Exception:
            raise HarnessFailure("checkpoint_unavailable") from None
