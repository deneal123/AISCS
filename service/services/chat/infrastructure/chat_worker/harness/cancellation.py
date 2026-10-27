"""Only backend-observed cancellation may settle through a stopped owner fence."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.infrastructure.chat_worker.execution.job_state import JobStateUnavailable
from service.services.chat.persistence.harness.result import read_result
from service.services.chat.persistence.harness.state import snapshot
from service.shared.task_contract import TaskResultV2


async def cancelled_projection(session, request, state, *, terminal_cancelled=False):
    if state.cancelled_execution is not True and terminal_cancelled is not True:
        raise JobStateUnavailable("Harness cancellation fenced")
    row = (
        (
            await session.execute(
                text(
                    "SELECT t.*,j.status AS job_status,j.payload AS job_payload "
                    "FROM profile.harness_task t "
                    "JOIN profile.user_launch j ON j.id=t.active_job_id "
                    "AND j.user_id=t.user_id AND j.type='CHAT' "
                    "WHERE t.task_id=:task AND t.active_job_id=:job AND t.user_id=:owner "
                    "AND t.thread_id=:thread AND t.execution_attempt_id=:attempt "
                    "AND t.fencing_epoch=:epoch AND j.status='PROCESSING' "
                    "AND j.payload->>'thread_id'=CAST(CAST(:thread AS uuid) AS text) "
                    "AND j.payload->>'_execution_attempt_v1'=CAST(CAST(:attempt AS uuid) AS text) "
                    "AND j.payload->>'_cancel_requested_v1'='true' FOR UPDATE OF t,j"
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
        raise JobStateUnavailable("Harness cancellation fenced")
    current = await snapshot(session, row)
    result = await read_result(session, row, current)
    if result is None and current.state is None:
        # Stop до фиксации критериев не создаёт фиктивный контракт или evidence.
        result = {
            "schema_version": 2,
            "status": "cancelled",
            "verified": False,
            "blocker": "cancelled",
            "confirmed": [],
            "unchecked": ["contract"],
            "references": [],
            "rounds": 0,
            "repair_cycles": 0,
        }
    projection = TaskResultV2.model_validate(result)
    if projection.status != "cancelled":
        raise JobStateUnavailable("Harness cancellation unavailable")
    state.cancelled_execution = True
    return projection.model_dump(mode="json")
