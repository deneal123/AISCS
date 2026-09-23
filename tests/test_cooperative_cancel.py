"""Кооперативная отмена: воркер сворачивается штатно по Redis-флагу, а не хард-киллом.

_run_with_cancel параллельно опрашивает chat:cancel:{task_id}; при флаге отменяет
исполнение и поднимает CancelledByUser → штатная очистка воркера (release резерва +
FAILURE + персист частичного ответа). Fail-open: нет redis / сбой опроса → не
отменяем. Флаг ставит JobApplicationService.cancel_task (+ revoke без хард-килла).

NB: E2E-поведение (реальный cancel-кнопкой прерывает стрим и чистит состояние)
проверяется на живом стеке; здесь — логика watcher'а и установки флага.
"""

import asyncio

import pytest

import service.services.chat.infrastructure.chat_worker_tasks as cwt
from service.services.jobs.application.job_application_service import _CANCEL_FLAG_TTL_SEC


class _Redis:
    # Синхронный клиент — как в воркере (redis.Redis); _run_with_cancel зовёт его
    # через asyncio.to_thread, поэтому методы НЕ async.
    def __init__(self, flag=None):
        self._flag = flag
        self.deleted: list = []

    def get(self, key):
        return self._flag

    def delete(self, key):
        self.deleted.append(key)
        self._flag = None


@pytest.mark.asyncio
async def test_run_with_cancel_returns_result_when_no_flag() -> None:
    async def _work():
        await asyncio.sleep(0.02)
        return {"reply": "done"}

    res = await cwt._run_with_cancel(
        _work(), redis_client=_Redis(flag=None), celery_task_id="t1", poll_interval=0.01
    )
    assert res == {"reply": "done"}


@pytest.mark.asyncio
async def test_run_with_cancel_raises_on_flag() -> None:
    async def _work():
        await asyncio.sleep(5)  # долгая работа — должна быть отменена
        return {"reply": "done"}

    redis = _Redis(flag="1")
    with pytest.raises(cwt.CancelledByUser):
        await cwt._run_with_cancel(
            _work(), redis_client=redis, celery_task_id="t1", poll_interval=0.01
        )
    assert redis.deleted == ["chat:cancel:t1"]  # флаг очищен после отмены


@pytest.mark.asyncio
async def test_run_with_cancel_no_redis_just_awaits() -> None:
    async def _work():
        return {"reply": "done"}

    res = await cwt._run_with_cancel(_work(), redis_client=None, celery_task_id="t1")
    assert res == {"reply": "done"}


@pytest.mark.asyncio
async def test_run_with_cancel_redis_error_does_not_cancel() -> None:
    class _BadRedis:
        def get(self, key):
            raise RuntimeError("redis down")

    async def _work():
        await asyncio.sleep(0.03)
        return {"reply": "done"}

    res = await cwt._run_with_cancel(
        _work(), redis_client=_BadRedis(), celery_task_id="t1", poll_interval=0.01
    )
    assert res == {"reply": "done"}  # сбой опроса → не отменяем, дожидаемся


@pytest.mark.asyncio
async def test_run_with_cancel_propagates_execution_error() -> None:
    async def _work():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await cwt._run_with_cancel(
            _work(), redis_client=_Redis(flag=None), celery_task_id="t1", poll_interval=0.01
        )


# --------------------------------------------------------------------------- #
# JobApplicationService.cancel_task — установка флага + revoke                 #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_cancel_task_sets_flag_and_revokes() -> None:
    from service.services.jobs.application.job_application_service import JobApplicationService

    calls: dict = {}

    class _Queue:
        def cancel_task(self, task_id):
            calls["revoked"] = task_id
            return True

    class _JobService:
        job_queue = _Queue()

    class _RedisSetter:
        async def set(self, key, val, ex=None):
            calls["flag"] = (key, val, ex)

    svc = JobApplicationService(job_service=_JobService(), redis_client=_RedisSetter())
    res = await svc.cancel_task("task-9")

    assert res == {"task_id": "task-9", "cancelled": True}
    assert calls["revoked"] == "task-9"
    assert calls["flag"][0] == "chat:cancel:task-9"
    assert calls["flag"][1] == "1"
    assert calls["flag"][2] == _CANCEL_FLAG_TTL_SEC


@pytest.mark.asyncio
async def test_cancel_task_without_redis_still_revokes() -> None:
    from service.services.jobs.application.job_application_service import JobApplicationService

    calls: dict = {}

    class _Queue:
        def cancel_task(self, task_id):
            calls["revoked"] = task_id
            return True

    class _JobService:
        job_queue = _Queue()

    svc = JobApplicationService(job_service=_JobService(), redis_client=None)
    res = await svc.cancel_task("task-9")

    assert res["cancelled"] is True
    assert calls["revoked"] == "task-9"  # без redis отмена всё равно доходит до revoke
