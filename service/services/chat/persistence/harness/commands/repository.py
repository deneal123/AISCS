"""Fenced IDE command admission and phase changes inside the existing journal."""

import time
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import text

from service.services.chat.application.harness_capability import require_dispatch, settings
from service.services.chat.domain.ide.commands import (
    TERMINAL_COMMAND_STATES,
    CommandRecord,
    CommandSpec,
)
from service.services.chat.domain.ide.runtime import allocation_generation_tag
from service.services.chat.persistence.harness.commands import state as records
from service.services.chat.persistence.harness.commands.completion import complete
from service.services.chat.persistence.harness.commands.pins import (
    attach_snapshot,
    release_snapshot,
)
from service.services.chat.persistence.harness.commands.recipes import bind_or_reject
from service.services.chat.persistence.harness.reservations import require_reconciled_cost
from service.services.chat.persistence.harness.runtime import HarnessRuntimeRepository
from service.services.chat.persistence.harness.state import (
    owned_row,
    require_active,
    require_known_cost,
    snapshot,
)
from service.shared.harness_protocol import HarnessFailure


async def current_generation(db, owner):
    row = (
        (
            await db.execute(
                text(
                    "SELECT w.allocation_id FROM profile.ide_repository_runtime w "
                    "JOIN profile.ide_repository r ON r.repository_id=w.repository_id "
                    "WHERE r.repository_id=:project AND r.user_id=:user_id "
                    "AND r.thread_id=:thread_id "
                    "AND w.state='ready' AND w.expires_at>extract(epoch FROM clock_timestamp()) "
                    "FOR SHARE OF w FOR UPDATE OF r"
                ),
                {**owner.params(), "project": UUID(owner.project_id)},
            )
        )
        .mappings()
        .first()
    )
    if row is None or allocation_generation_tag(row["allocation_id"]) != owner.generation:
        raise HarnessFailure("binding_changed")


class IdeCommandRepository(HarnessRuntimeRepository):
    async def reject_invalid_command(self, owner, operation_id, arguments):
        from service.services.chat.persistence.harness.commands.validation import reject_invalid

        return await self._transaction(
            lambda db: reject_invalid(db, owner, operation_id, arguments)
        )

    async def admit_command(self, owner, operation_id, spec, workspace_id):
        async def operation(db):
            row = await owned_row(db, owner)
            require_active(row)
            current = await snapshot(db, row)
            require_dispatch(current.admission)
            if not settings().ide_commands_enabled:
                raise HarnessFailure("dispatch_disabled")
            if current.state is None or "exec" not in current.state.contract.actions:
                raise HarnessFailure("task_permission_denied")
            if current.admission.surface != "ide":
                raise HarnessFailure("task_permission_denied")
            await current_generation(db, owner)
            await self._funds(db, current)
            await require_reconciled_cost(
                db, row["task_id"], except_operation_id=uuid5(operation_id, "billing")
            )
            effect = (
                (
                    await db.execute(
                        text(
                            "SELECT intent,status,command FROM profile.harness_operation "
                            "WHERE task_id=:task AND operation_id=:operation FOR UPDATE"
                        ),
                        {"task": row["task_id"], "operation": operation_id},
                    )
                )
                .mappings()
                .first()
            )
            if effect is None or effect["intent"]["action"] != "exec":
                raise HarnessFailure("operation_conflict")
            if effect["intent"]["name"] != "ide_run_command":
                raise HarnessFailure("operation_conflict")
            try:
                canonical_spec = CommandSpec.model_validate_json(effect["intent"]["arguments"])
            except ValidationError:
                raise HarnessFailure("operation_conflict") from None
            if canonical_spec != spec:
                raise HarnessFailure("operation_conflict")
            if effect["command"] is not None:
                saved = CommandRecord.model_validate(effect["command"])
                if saved.spec != spec or saved.workspace_id != workspace_id:
                    raise HarnessFailure("operation_conflict")
                return saved
            if effect["status"] != "dispatched":
                raise HarnessFailure("operation_unknown")
            busy = await db.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM profile.harness_operation "
                    "WHERE command_repository_id=:project AND command_state IN "
                    "('preparing','ready','dispatching','running','stopping','unknown'))"
                ),
                {"project": UUID(owner.project_id)},
            )
            if busy:
                raise HarnessFailure("operation_conflict")
            rejection = await bind_or_reject(db, row, current, spec, operation_id)
            if rejection is not None:
                return rejection
            saved = CommandRecord(
                operation_id=operation_id,
                task_id=row["task_id"],
                repository_id=UUID(owner.project_id),
                workspace_id=workspace_id,
                generation=owner.generation,
                attempt_id=UUID(owner.attempt_id),
                epoch=owner.epoch,
                deadline_at=time.time()
                + (current.state.contract.active_limit_ms - current.state.budget.active_ms) / 1000,
                spec=spec,
            )
            await db.execute(
                text(
                    "UPDATE profile.harness_operation SET command=CAST(:body AS jsonb),"
                    "command_state='preparing',command_repository_id=:project,"
                    "command_workspace_id=:ws "
                    "WHERE task_id=:task AND operation_id=:operation"
                ),
                {
                    "body": saved.model_dump_json(),
                    "project": saved.repository_id,
                    "ws": workspace_id,
                    "task": saved.task_id,
                    "operation": operation_id,
                },
            )
            return saved

        result = await self._transaction(operation)
        if isinstance(result, HarnessFailure):
            raise result from None
        return result

    async def command_status(self, owner, operation_id):
        async def operation(db):
            await owned_row(db, owner)
            return await records.read(db, UUID(owner.task_id), operation_id)

        return await self._transaction(operation)

    async def transition(
        self,
        owner,
        operation_id,
        *,
        expected_phase=None,
        observed_revision=None,
        files=None,
        **updates,
    ):
        async def operation(db):
            row = await owned_row(db, owner)
            old = await records.read(db, row["task_id"], operation_id)
            if expected_phase is not None and old.engine_phase != expected_phase:
                raise HarnessFailure("operation_unknown")
            try:
                new = old.advance(**updates)
            except ValidationError:
                raise HarnessFailure("verification_missing") from None
            dispatch = new.state == "running" and old.state == "dispatching"
            if new.state in {"ready", "dispatching"} or dispatch:
                require_active(row)
                current = await snapshot(db, row)
                require_dispatch(current.admission)
                if not settings().ide_commands_enabled:
                    raise HarnessFailure("dispatch_disabled")
                await current_generation(db, owner)
                await self._funds(db, current)
                await require_known_cost(db, row["task_id"])
                if old.attempt_id != UUID(owner.attempt_id) or old.epoch != owner.epoch:
                    raise HarnessFailure("harness_fenced")
                if current.state.budget.active_ms >= current.state.contract.active_limit_ms:
                    raise HarnessFailure("deadline_exceeded")
                if old.deadline_at is not None and time.time() >= old.deadline_at:
                    raise HarnessFailure("deadline_exceeded")
                if (
                    dispatch
                    and old.supervisor is not None
                    and observed_revision != old.source_revision
                ):
                    raise HarnessFailure("binding_changed")
            if new.state == "completed" and old.state not in TERMINAL_COMMAND_STATES:
                # Serialize publication with Stop/ownership and repository generation,
                # not just the earlier admission. Cleanup can still be recorded.
                try:
                    require_active(row)
                    await current_generation(db, owner)
                    if old.deadline_at and time.time() >= old.deadline_at:
                        raise HarnessFailure("deadline_exceeded")
                except HarnessFailure as error:
                    reason = error.code
                    new = new.advance(
                        state="failed"
                        if reason in {"binding_changed", "deadline_exceeded"}
                        else "cancelled",
                        failure_reason=reason
                        if reason in {"binding_changed", "deadline_exceeded"}
                        else "",
                        final_revision=None if reason == "binding_changed" else new.final_revision,
                        verification={"status": "blocked", "reason": reason},
                    )
            await records.save(db, old, new)
            if new.state in TERMINAL_COMMAND_STATES and old.state not in TERMINAL_COMMAND_STATES:
                # Process completion is not criterion verification. No command
                # evidence is minted here merely because an exit code is zero.
                await complete(db, row, new, files or {})
                await release_snapshot(db, old)
            return new

        return await self._transaction(operation)

    async def pin_snapshot(self, owner, operation_id, checkpoint_id, digest, revision):
        async def operation(db):
            return await attach_snapshot(db, owner, operation_id, checkpoint_id, digest, revision)

        return await self._transaction(operation)
