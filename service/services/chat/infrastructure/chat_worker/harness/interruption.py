"""Повторяется доставка задания, а не команда, запись или платный вызов."""

from datetime import UTC, datetime

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.infrastructure.chat_worker.execution.preflight import (
    abort_unverified_job,
)
from service.services.chat.persistence.harness.retry import MAX_RETRIES, HarnessRetryRepository
from service.shared.harness_protocol import HarnessFailure


async def recover_interrupted_run(*, connector, session, request, state, publisher):
    try:
        await session.rollback()
        if not request.celery_task_id:
            raise HarnessFailure("checkpoint_unavailable")
        decision, result = await HarnessRetryRepository(connector).prepare(
            task_id=state.harness_task_id,
            job_id=request.job_id,
            user_id=request.user_id,
            thread_id=request.thread_id,
            attempt_id=state.execution_attempt_id,
            epoch=state.harness_epoch,
        )
    except Exception:
        return await abort_unverified_job(
            session=session,
            publisher=publisher,
            error=JobStateUnavailable("Harness recovery unavailable"),
            job_id=request.job_id,
        )
    pending = decision["state"] == "pending"
    message = (
        "Связь с исполнителем прервалась. Восстанавливаю то же задание."
        if pending
        else "Не удалось восстановить связь с исполнителем. Подтверждённые изменения сохранены."
    )
    payload = {
        "type": "status_update" if pending else "error",
        "job_id": request.job_id,
        "message": message,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if not pending:
        payload.update(error=message, error_code="job_service_unavailable", status_code=503)
        if result:
            payload["metadata"] = {"task_result": result}
    try:
        publisher.publish_payload(payload)
    except Exception:
        pass  # Только уведомление; committed intent и late-ack доставка остаются авторитетными.
    return {
        **payload,
        "status": "recovery_pending" if pending else "error",
        "recovery_retry_count": decision["count"],
    }


def retry_delivery(task, result):
    if result.get("status") == "recovery_pending":
        count = result.get("recovery_retry_count")
        if type(count) is not int or not 1 <= count <= MAX_RETRIES:
            raise HarnessFailure("checkpoint_conflict")
        # retry сохраняет task ID, kwargs и маршрут исходной доставки. Лимит3
        # хранится в PostgreSQL, не обнуляется новой доставкой или рестартом worker.
        # Холодный запуск исполнителя не должен исчерпывать все доставки за6 секунд.
        # Пауза зависит от подтверждённого счётчика задания, не от памяти Celery.
        raise task.retry(countdown=3**count, max_retries=MAX_RETRIES)
    return result
