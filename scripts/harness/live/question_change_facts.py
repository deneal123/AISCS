"""Состояние одного синтетического задания, без вывода transcript и секретов."""

from sqlalchemy import text

from service.shared.task_contract import TaskState


async def facts(container, scope, root, child=None):
    async with container.infra.pg_connector.get_session_context() as db:
        task = (
            (
                await db.execute(
                    text("SELECT * FROM profile.harness_task WHERE task_id=:root"), {"root": root}
                )
            )
            .mappings()
            .one()
        )
        operations = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM profile.harness_operation "
                        "WHERE task_id=:root ORDER BY operation_id"
                    ),
                    {"root": root},
                )
            )
            .mappings()
            .all()
        )
        grants = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM profile.harness_grant "
                        "WHERE task_id=:root ORDER BY operation_id"
                    ),
                    {"root": root},
                )
            )
            .mappings()
            .all()
        )
        jobs = (
            (
                await db.execute(
                    text(
                        "SELECT id,status,payload FROM profile.user_launch "
                        "WHERE id IN (:root,:child) ORDER BY id"
                    ),
                    {"root": root, "child": child or root},
                )
            )
            .mappings()
            .all()
        )
        charges = (
            (
                await db.execute(
                    text("SELECT * FROM profile.billing_events WHERE user_id=:owner ORDER BY id"),
                    {"owner": scope.user_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "task": dict(task),
        "operations": [dict(row) for row in operations],
        "grants": [dict(row) for row in grants],
        "jobs": [dict(row) for row in jobs],
        "charges": [dict(row) for row in charges],
    }, TaskState.model_validate(task["checkpoint"]["state"])
