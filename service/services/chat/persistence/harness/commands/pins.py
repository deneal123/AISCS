"""Checkpoint pins share publication/retention locks and commit with command state."""

from uuid import UUID

from sqlalchemy import text

from service.services.chat.domain.ide.runtime import allocation_generation_tag
from service.services.chat.persistence.harness.commands import state as records
from service.services.chat.persistence.harness.state import owned_row, require_active
from service.shared.harness_protocol import HarnessFailure


async def attach_snapshot(db, owner, operation_id, checkpoint_id, digest, source_revision):
    row = await owned_row(db, owner)
    require_active(row)
    command = await records.read(db, row["task_id"], operation_id)
    if command.snapshot_id is not None:
        if (command.snapshot_id, command.snapshot_digest, command.source_revision) != (
            checkpoint_id,
            digest,
            source_revision,
        ):
            raise HarnessFailure("operation_conflict")
        return command
    if command.state != "preparing":
        raise HarnessFailure("operation_unknown")
    locked_project = await db.scalar(
        text(
            "SELECT repository_id FROM profile.ide_repository "
            "WHERE repository_id=:project FOR UPDATE"
        ),
        {"project": command.repository_id},
    )
    if locked_project is None:
        raise HarnessFailure("binding_changed")
    checkpoint = (
        (
            await db.execute(
                text(
                    "SELECT allocation_id FROM profile.ide_checkpoint_intent "
                    "WHERE repository_id=:project AND checkpoint_id=:checkpoint AND user_id=:owner "
                    "AND thread_id=:thread AND state='published' AND sha256=:digest "
                    "AND upload_settled_at IS NOT NULL AND collected_at IS NULL FOR UPDATE"
                ),
                {
                    "project": command.repository_id,
                    "checkpoint": checkpoint_id,
                    "owner": UUID(owner.user_id),
                    "thread": UUID(owner.thread_id),
                    "digest": digest,
                },
            )
        )
        .mappings()
        .first()
    )
    if (
        checkpoint is None
        or allocation_generation_tag(checkpoint["allocation_id"]) != owner.generation
    ):
        raise HarnessFailure("verification_unavailable")
    updated = command.advance(
        snapshot_id=checkpoint_id, snapshot_digest=digest, source_revision=source_revision
    )
    await db.execute(
        text(
            "UPDATE profile.ide_checkpoint_intent SET command_pins=command_pins+1 "
            "WHERE repository_id=:project AND checkpoint_id=:checkpoint"
        ),
        {"project": command.repository_id, "checkpoint": checkpoint_id},
    )
    await records.save(db, command, updated)
    return updated


async def release_snapshot(db, command):
    """Caller has confirmed process cleanup and is committing a terminal transition."""
    if command.snapshot_id is None:
        return
    result = await db.scalar(
        text(
            "UPDATE profile.ide_checkpoint_intent SET command_pins=command_pins-1 "
            "WHERE repository_id=:project AND checkpoint_id=:checkpoint AND command_pins>0 "
            "RETURNING checkpoint_id"
        ),
        {"project": command.repository_id, "checkpoint": command.snapshot_id},
    )
    if result != command.snapshot_id:
        raise HarnessFailure("operation_conflict")
