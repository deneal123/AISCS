"""Bounded owner-only console projection; no execution identities or capabilities."""

from sqlalchemy import text

from service.services.chat.domain.ide.commands import CommandRecord


async def history(connector, scope, generation):
    async with connector.get_session_context() as db:
        rows = (
            (
                await db.execute(
                    text(
                        "SELECT c.command FROM profile.harness_operation c "
                        "JOIN profile.harness_task t ON t.task_id=c.task_id "
                        "WHERE t.user_id=:user AND t.thread_id=:thread "
                        "AND c.command_repository_id=:repository "
                        "AND c.command->>'generation'=:generation "
                        "ORDER BY c.created_at DESC,c.operation_id DESC LIMIT 30"
                    ),
                    {
                        "user": scope.user_id,
                        "thread": scope.thread_id,
                        "repository": scope.repository_id,
                        "generation": generation,
                    },
                )
            )
            .scalars()
            .all()
        )
    entries = []
    for raw in reversed(rows):
        record = CommandRecord.model_validate(raw)
        entries.append(
            {
                "id": str(record.operation_id),
                "state": record.state,
                "profile": record.spec.profile,
                "target": record.spec.target,
                "result": record.result.model_dump() if record.result else None,
                "verification": record.verification,
                "blocker": record.failure_reason,
            }
        )
    return {"repository_id": str(scope.repository_id), "generation": generation, "entries": entries}
