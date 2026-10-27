"""Mutation exclusion is a PostgreSQL fact, not a Redis lease timeout."""

from sqlalchemy import text

from service.services.chat.application.workspace_collaboration import CollaborationConflict


class IdeCommandBusy(CollaborationConflict):
    code = "ide_command_busy"


async def project_is_busy(db, repository_id):
    """Caller holds the project row lock, shared with command admission."""
    return await db.scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM profile.harness_operation "
            "WHERE command_repository_id=:project AND command_state IN "
            "('preparing','ready','dispatching','running','stopping','unknown'))"
        ),
        {"project": repository_id},
    )


async def require_mutation_available(connector, workspace_id, mutation):
    # Capture is read-only. Its separately confirmed publication is not a source write.
    if mutation == "capture":
        return
    try:
        async with connector.get_session_context() as db:
            busy = await db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM profile.harness_operation "
                    "WHERE command_workspace_id=:workspace AND command_state IN "
                    "('preparing','ready','dispatching','running','stopping','unknown'))"
                ),
                {"workspace": workspace_id},
            )
    except Exception:
        from service.services.chat.application.workspace_collaboration import (
            CollaborationUnavailable,
        )

        raise CollaborationUnavailable() from None
    if busy:
        raise IdeCommandBusy()
