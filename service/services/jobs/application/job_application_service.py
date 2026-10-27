from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from service.models.auth_models import AuthProfile
from service.models.jobs_models import JobLogic
from service.models.key_value import ProcessingStatus
from service.services.jobs.application.dto import StartJobRequest, TaskStatusResponse
from service.services.jobs.application.job_service import JobService, _worker_owns_terminal
from service.services.jobs.persistence.transitions import HARNESS_RETRY_KEY

logger = logging.getLogger(__name__)

# Флаг кооперативной отмены живёт недолго: воркер либо увидит его в стрим-цикле и
# свернётся, либо задача завершится сама. TTL страхует от «залипшего» флага.
_CANCEL_FLAG_TTL_SEC = 120


class JobApplicationService:
    def __init__(self, job_service: JobService, redis_client: Any | None = None) -> None:
        self._job_service = job_service
        self._redis_client = redis_client

    async def start_job(self, profile: AuthProfile, request: StartJobRequest):
        return await self._job_service.create_job(profile.user_id, request)

    async def fetch_result(self, profile: AuthProfile, job_id: str):
        try:
            parsed_job_id = UUID(job_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid job_id format",
            ) from exc
        return await self._job_service.fetch_job_result(profile.user_id, parsed_job_id)

    async def _require_owned_task(self, task_id: str, user_id: UUID) -> JobLogic:
        if (
            not isinstance(user_id, UUID)
            or user_id.int == 0
            or not isinstance(task_id, str)
            or not 1 <= len(task_id) <= 128
            or any(ord(char) < 32 for char in task_id)
        ):
            raise HTTPException(status_code=404, detail="Task not found")
        try:
            job = await self._job_service.repository.fetch_job_by_task_id(task_id, user_id)
        except Exception:
            logger.warning(
                "task ownership unavailable",
                extra={
                    "component": "task_control",
                    "failure_code": "unavailable",
                },
            )
            raise HTTPException(status_code=503, detail="Task service unavailable") from None
        if job is None or job.user_id != user_id:
            raise HTTPException(status_code=404, detail="Task not found")
        return job

    async def get_task_status(self, task_id: str, *, user_id: UUID) -> TaskStatusResponse:
        job = await self._require_owned_task(task_id, user_id)
        if _worker_owns_terminal(job):
            # Celery results may contain private provider/materialization data.
            # Chat content is served by its canonical message endpoint, not here.
            recovery = (job.payload or {}).get(HARNESS_RETRY_KEY) or {}
            blocked = (
                job.status == ProcessingStatus.PROCESSING and recovery.get("state") == "blocked"
            )
            return TaskStatusResponse(
                task_id=task_id,
                state="FAILURE"
                if blocked
                else {
                    ProcessingStatus.NEW: "PENDING",
                    ProcessingStatus.PROCESSING: "STARTED",
                    ProcessingStatus.SUCCESS: "SUCCESS",
                    ProcessingStatus.FAILURE: "FAILURE",
                }[job.status],
                progress=None,
                status="Восстановление задания заблокировано. Подтверждённые данные сохранены."
                if blocked
                else None,
                result=None,
                error=(
                    "Связь с исполнителем недоступна."
                    if blocked
                    else "Task failed"
                    if job.status == ProcessingStatus.FAILURE
                    else None
                ),
            )
        queue = self._job_service.job_queue
        if queue is None:
            return TaskStatusResponse(
                task_id=task_id,
                state="UNAVAILABLE",
                progress=None,
                status="Celery queue is disabled",
                result=None,
                error=None,
            )

        ready, successful, result_payload, meta, state = queue.get_task_state(task_id)
        meta_dict = meta if isinstance(meta, dict) else {}
        payload_dict = result_payload if isinstance(result_payload, dict) else None

        error_text: str | None = None
        if ready and not successful:
            if isinstance(result_payload, Exception):
                error_text = str(result_payload)
            elif isinstance(result_payload, str):
                error_text = result_payload

        return TaskStatusResponse(
            task_id=task_id,
            state=state,
            progress=meta_dict.get("progress"),
            status=meta_dict.get("status"),
            result=payload_dict if ready and successful else None,
            error=error_text,
        )

    async def _set_cancel_flag(self, task_id: str) -> bool:
        """Acknowledge the request, not completion of worker cancellation."""
        if self._redis_client is None:
            return False
        try:
            return (
                await self._redis_client.set(f"chat:cancel:{task_id}", "1", ex=_CANCEL_FLAG_TTL_SEC)
            ) is True
        except Exception:
            logger.debug(
                "cooperative cancel flag unavailable",
                extra={"component": "task_control", "failure_code": "unavailable"},
            )
            return False

    async def cancel_task(self, task_id: str, *, user_id: UUID) -> dict[str, str | bool]:
        job = await self._require_owned_task(task_id, user_id)
        if job.status in (ProcessingStatus.SUCCESS, ProcessingStatus.FAILURE) or any(
            key in (job.payload or {})
            for key in ("_accepted_turn_v1", "_prepared_turn_v1", "_materialization_plan_v1")
        ):
            # Accepted usage still needs settlement/materialization. Revoking its
            # redelivery would strand that recovery; completed results are immutable.
            return {"task_id": task_id, "cancelled": False}
        try:
            if _worker_owns_terminal(job):
                if job.status == ProcessingStatus.NEW and isinstance(
                    (job.payload or {}).get("_human_question_parent_v1"), dict
                ):
                    # Waiting for consent deliberately has no worker. Finish only
                    # when the owned DB row still proves that execution never began.
                    stopped = await self._job_service.repository.cancel_unstarted_question(
                        job.id, user_id
                    )
                    if stopped:
                        return {"task_id": task_id, "cancelled": True}
                # A worker may accept a result after our SQL read. Revoke would
                # discard its later redelivery and strand usage settlement.
                # Only the worker can choose cancel versus completed execution;
                # its recovery path restores accepted facts before model work.
                if not await self._set_cancel_flag(task_id):
                    raise RuntimeError("Cooperative cancellation unavailable")
                requested = await self._job_service.repository.request_chat_cancel(job.id, user_id)
                return {"task_id": task_id, "cancelled": requested}
            queue = self._job_service.job_queue
            if queue is None:
                raise RuntimeError("Job queue is disabled")
            # Legacy non-thread jobs retain their existing queue cancellation.
            await self._set_cancel_flag(task_id)
            queue.cancel_task(task_id)
            return {"task_id": task_id, "cancelled": True}
        except Exception:  # noqa: BLE001
            logger.warning(
                "task cancel unavailable",
                extra={
                    "component": "task_control",
                    "failure_code": "unavailable",
                },
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Celery is unavailable",
            ) from None
