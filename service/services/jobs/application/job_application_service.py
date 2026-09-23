from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from service.models.auth_models import AuthProfile
from service.services.jobs.application.dto import StartJobRequest, TaskStatusResponse
from service.services.jobs.application.job_service import JobService

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

    async def get_task_status(self, task_id: str) -> TaskStatusResponse:
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

    async def _set_cancel_flag(self, task_id: str) -> None:
        """Redis-флаг кооперативной отмены; воркер проверяет его в стрим-цикле.
        Best-effort: сбой не мешает revoke (жёсткому фолбэку выше по стеку)."""
        if self._redis_client is None:
            return
        try:
            await self._redis_client.set(f"chat:cancel:{task_id}", "1", ex=_CANCEL_FLAG_TTL_SEC)
        except Exception:
            logger.debug(
                "Failed to set cancel flag for %s (cooperative cancel best-effort)",
                task_id,
                exc_info=True,
            )

    async def cancel_task(self, task_id: str) -> dict[str, str | bool]:
        try:
            queue = self._job_service.job_queue
            if queue is None:
                raise RuntimeError("Job queue is disabled")
            # Кооперативная отмена: сперва ставим Redis-флаг (воркер свернётся штатно),
            # затем revoke(terminate=False) — чтобы задача не переисполнилась.
            await self._set_cancel_flag(task_id)
            queue.cancel_task(task_id)
            return {"task_id": task_id, "cancelled": True}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Celery task cancel failed for %s: %s", task_id, exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Celery is unavailable",
            ) from exc
