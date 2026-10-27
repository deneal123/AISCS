"""Read-only recovery inventory and narrowly scoped retirement authority."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.application.harness_capability import HarnessOwner
from service.services.chat.domain.ide.commands import CommandRecord
from service.shared.harness_protocol import HarnessFailure


async def candidates(connector, after=None):
    cursor = after or (UUID(int=0), UUID(int=0))
    async with connector.get_session_context() as db:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT t.task_id,t.active_job_id,t.user_id,t.thread_id,"
                        "t.execution_attempt_id,t.fencing_epoch,t.admission,"
                        "c.operation_id,j.status "
                        "FROM profile.harness_operation c "
                        "JOIN profile.harness_task t ON t.task_id=c.task_id "
                        "JOIN profile.user_launch j ON j.id=t.active_job_id "
                        "WHERE c.command_state IN "
                        "('preparing','ready','dispatching','running','stopping','unknown') "
                        "AND (t.task_id,c.operation_id)>(:task,:operation) "
                        "ORDER BY t.task_id,c.operation_id LIMIT 16"
                    ),
                    {"task": cursor[0], "operation": cursor[1]},
                )
            )
            .mappings()
            .all()
        )
    return [
        (
            HarnessOwner(
                task_id=str(row["task_id"]),
                job_id=str(row["active_job_id"]),
                user_id=str(row["user_id"]),
                thread_id=str(row["thread_id"]),
                attempt_id=str(row["execution_attempt_id"]),
                epoch=row["fencing_epoch"],
                project_id=row["admission"]["project_id"],
                generation=row["admission"]["generation"],
            ),
            row["operation_id"],
            row["status"] != "PROCESSING",
        )
        for row in rows
    ]


async def stop_binding(connector, owner, operation_id):
    """A fenced attempt may stop its own old process, never dispatch or publish."""
    async with connector.get_session_context() as db:
        raw = await db.scalar(
            text(
                "SELECT c.command FROM profile.harness_operation c "
                "JOIN profile.harness_task t ON t.task_id=c.task_id "
                "WHERE t.task_id=:task_id AND t.user_id=:user_id AND t.thread_id=:thread_id "
                "AND c.operation_id=:operation"
            ),
            {**owner.params(), "operation": operation_id},
        )
    if raw is None:
        raise HarnessFailure("harness_fenced")
    record = CommandRecord.model_validate(raw)
    if (
        record.attempt_id != UUID(owner.attempt_id)
        or record.epoch != owner.epoch
        or str(record.repository_id) != owner.project_id
        or record.generation != owner.generation
    ):
        raise HarnessFailure("harness_fenced")
    return record
