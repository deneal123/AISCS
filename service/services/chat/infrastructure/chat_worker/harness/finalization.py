"""Публичные критерии свежего terminal берутся из текущего backend-журнала."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.persistence.harness.result import read_result
from service.services.chat.persistence.harness.state import snapshot
from service.shared.task_contract import TaskResultV2

_UNRESOLVED = {"cost_unknown", "operation_unknown", "cancelled"}
UNVERIFIED_REPLY = "Задание не завершено: сервер не подтвердил актуальность результата."


def protect_displayed_reply(canonical, before, after):
    reported, current = before.get("task_result") or {}, after.get("task_result") or {}
    if reported.get("status") == "completed" and current.get("status") != "completed":
        return UNVERIFIED_REPLY
    return canonical


def merge_projection(authoritative, reported):
    result = dict(authoritative)
    # Сервер уточняет evidence, но не превращает остановку/вопрос исполнителя в
    # успех. Неизвестный расход и эффект важнее менее существенного блокера.
    if isinstance(reported, dict) and reported.get("schema_version") == 2:
        original = TaskResultV2.model_validate(reported)
        if original.status != "completed" and result.get("blocker") not in _UNRESOLVED:
            result.update(status=original.status, verified=False, blocker=original.blocker)
    return TaskResultV2.model_validate(result).model_dump(mode="json")


def missing_contract_projection(reported):
    original = (
        TaskResultV2.model_validate(reported)
        if isinstance(reported, dict) and reported.get("schema_version") == 2
        else None
    )
    if original is not None and original.status != "completed" and not original.confirmed:
        return original.model_dump(mode="json")
    return {
        "schema_version": 2,
        "status": "blocked",
        "verified": False,
        "blocker": "task_contract_invalid",
        "confirmed": [],
        "unchecked": ["contract"],
        "references": [],
        "rounds": 0,
        "repair_cycles": 0,
    }


async def project_current_result(session, request, state, metadata):
    if not state.harness_task_id:
        return metadata
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.*,j.status AS job_status,j.payload AS job_payload "
                    "FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id AND j.user_id=t.user_id "
                    "WHERE t.task_id=:task AND t.active_job_id=:job AND t.user_id=:owner "
                    "AND t.thread_id=:thread AND t.execution_attempt_id=:attempt "
                    "AND t.fencing_epoch=:epoch "
                    "AND j.type='CHAT' AND j.status='PROCESSING' "
                    "AND j.payload->>'thread_id'=CAST(CAST(:thread AS uuid) AS text) "
                    "AND j.payload->>'_execution_attempt_v1'=CAST(CAST(:attempt AS uuid) AS text) "
                    "FOR UPDATE OF t,j"
                ),
                {
                    "task": UUID(state.harness_task_id),
                    "job": UUID(request.job_id),
                    "owner": UUID(str(request.user_id)),
                    "thread": UUID(request.thread_id),
                    "attempt": UUID(state.execution_attempt_id),
                    "epoch": state.harness_epoch,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise JobStateUnavailable("Harness completion fenced")
    current = await snapshot(session, row)
    authoritative = await read_result(session, row, current)
    if authoritative is None:
        # До seal ещё нет критериев: существующий проверенный admission blocker
        # сохраняется, никакого фиктивного completed backend не создаёт.
        result = missing_contract_projection(metadata.get("task_result"))
    else:
        result = merge_projection(authoritative, metadata.get("task_result"))
    projected = {**metadata, "task_result": result}
    if result["status"] != "completed" and projected.get("execution_status") == "completed":
        projected["execution_status"] = "partial"
    return projected
