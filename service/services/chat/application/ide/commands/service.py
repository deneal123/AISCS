"""Console agent entry: durable preparation, addressable execution and observation."""

import asyncio
import logging
import time
from uuid import UUID, uuid5

from service.infrastructure.ide.transports.commands import command_request
from service.services.chat.application.ide.checkpoints.capture import capture_checkpoint
from service.services.chat.application.workspace_event_projection import (
    publish_workspace_invalidation,
)
from service.services.chat.domain.ide.commands import TERMINAL_COMMAND_STATES
from service.services.chat.domain.ide.console import CommandResult
from service.services.chat.domain.ide.runtime import RepositoryScope, generation_tag
from service.services.chat.domain.ide.verification import verify
from service.services.chat.persistence.harness.commands.repository import IdeCommandRepository
from service.shared.harness_protocol import Exchange, HarnessFailure

logger = logging.getLogger("gpthub.ide.command")
_FAILURES = frozenset(
    {
        "workspace_conflict",
        "workspace_unavailable",
        "workspace_forbidden",
        "driver_failed",
        "invalid_request",
        "checkpoint_unavailable",
        "operation_conflict",
        "binding_changed",
        "verification_missing",
        "deadline_exceeded",
        "dispatch_disabled",
        "harness_fenced",
    }
)


def view(record):
    return {
        "operation_id": str(record.operation_id),
        "state": record.state,
        "verification": record.verification,
        "source_revision": record.source_revision,
        "final_revision": record.final_revision,
        "blocker": record.failure_reason,
        "result": record.result.model_dump() if record.result else None,
    }


class AgentConsole:
    def __init__(self, console, saved, infra):
        self.console, self.saved, self.infra = console, saved, infra
        self.repo = IdeCommandRepository(infra.pg_connector)

    @staticmethod
    def scope(owner):
        return RepositoryScope(UUID(owner.thread_id), UUID(owner.user_id), UUID(owner.project_id))

    async def binding(self, owner):
        resolved = await self.console.runtime.resolve(self.scope(owner))
        if generation_tag(resolved.attempt) != owner.generation:
            raise HarnessFailure("binding_changed")
        return resolved.binding

    async def request(self, owner, binding, record, action, capability, **fields):
        return await command_request(
            self.console.runtime.client,
            owner,
            binding,
            record,
            action,
            capability,
            self.saved.limits,
            **fields,
        )

    async def run(self, owner, operation_id, spec, capability):
        binding = await self.binding(owner)
        record = await self.repo.admit_command(owner, operation_id, spec, binding.workspace_id)
        if record.state != "preparing" or record.engine_phase != "unclaimed":
            return await self.status(owner, operation_id, capability)
        try:
            rows = await self.saved.checkpoints.repository.inventory(self.scope(owner))
            base = rows[0]["current_checkpoint_id"] if rows else None
            checkpoint = await capture_checkpoint(
                self.saved.edits,
                self.saved.checkpoints,
                self.scope(owner),
                checkpoint_id=uuid5(operation_id, "command-snapshot"),
                base_checkpoint_id=base,
                generation=owner.generation,
                session="agent-command-" + owner.task_id.replace("-", ""),
                limits=self.saved.limits,
            )
            if checkpoint.state != "published" or not checkpoint.upload_settled:
                raise HarnessFailure("verification_unavailable")
            record = await self.repo.pin_snapshot(
                owner,
                operation_id,
                checkpoint.intent.blob.checkpoint_id,
                checkpoint.intent.blob.sha256,
                checkpoint.intent.blob.sha256,
            )
            record = await self.repo.transition(owner, operation_id, state="ready")
            record = await self.repo.transition(
                owner, operation_id, expected_phase="unclaimed", engine_phase="creating"
            )
            engine = await self.request(owner, binding, record, "create", capability)
            record = await self.repo.transition(
                owner,
                operation_id,
                expected_phase="creating",
                engine_phase="created",
                engine_id=engine["engine_id"],
                container_id=engine["container_id"],
            )
            record = await self.repo.transition(
                owner,
                operation_id,
                expected_phase="created",
                engine_phase="handshaking",
                state="dispatching",
            )
            ready = await self.request(owner, binding, record, "handshake", capability)
            record = await self.repo.transition(
                owner,
                operation_id,
                expected_phase="handshaking",
                engine_phase="waiting",
                supervisor=ready["supervisor"],
            )
            self.watch(owner, operation_id, capability, binding=binding, fallback=record)
            argv = (
                ["/bin/sh", "-c", spec.command]
                if spec.profile == "shell"
                else ["python3", spec.target]
            )
            timeout = min(
                spec.timeout_sec, record.deadline_at - time.time(), binding.expires_at - time.time()
            )
            if timeout <= 0:
                raise HarnessFailure("deadline_exceeded")
            await self.request(
                owner,
                binding,
                record,
                "dispatch",
                capability,
                argv=argv,
                timeout_sec=timeout,
                verification_profile=spec.profile
                if spec.profile in {"unittest", "pytest"}
                else None,
                verification_target=spec.target,
            )
            return await self.status(owner, operation_id, capability)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            code = getattr(error, "code", None)
            logger.warning(
                "Command preparation or dispatch unconfirmed",
                extra={
                    "component": "ide_command",
                    "phase": record.engine_phase,
                    "failure_code": code
                    if isinstance(code, str) and code in _FAILURES
                    else "unconfirmed",
                },
            )
            record = await self.repo.command_status(owner, operation_id)
            if record.engine_phase == "unclaimed" and record.engine_id is None:
                return view(
                    await self.repo.transition(
                        owner,
                        operation_id,
                        state="failed",
                        cleanup_confirmed=True,
                        failure_reason="preparation_failed",
                        verification={"status": "blocked", "reason": "snapshot_unavailable"},
                    )
                )
            if record.state not in TERMINAL_COMMAND_STATES and record.state != "unknown":
                updates = {"state": "unknown"}
                if record.engine_phase != "unclaimed":
                    updates["engine_phase"] = "unknown"
                record = await self.repo.transition(owner, operation_id, **updates)
            return view(record)

    def watch(self, owner, operation_id, capability, *, binding=None, fallback=None):
        manager = self.infra.background_task_manager
        name = "ide-command:" + str(operation_id)
        if any(not task.done() and task.get_name() == name for task in manager.tasks):
            return

        async def observe():
            try:
                async with asyncio.timeout(180):
                    while True:
                        try:
                            data = await self.status(owner, operation_id, capability)
                        except HarnessFailure as error:
                            if error.code == "harness_fenced" and binding and fallback:
                                await self.request(owner, binding, fallback, "stop", capability)
                                return
                            await asyncio.sleep(0.5)
                            continue
                        except Exception:
                            await asyncio.sleep(0.5)
                            continue
                        if data["state"] in TERMINAL_COMMAND_STATES:
                            return
                        await asyncio.sleep(0.5)
            except (Exception, asyncio.CancelledError):
                # Observation is retryable; starting the command is not. The
                # durable gate survives this task/backend process disappearing.
                return

        manager.tasks.append(asyncio.create_task(observe(), name=name))

    async def status(self, owner, operation_id, capability, *, stop=False):
        record = await self.repo.command_status(owner, operation_id)
        if record.state in TERMINAL_COMMAND_STATES:
            return view(record)
        current = (await self.repo.exchange(owner, Exchange(opcode="state")))["snapshot"]
        cancelled = stop or current["stopped"] or record.stop_reason == "cancelled"
        expired = bool(record.deadline_at and time.time() >= record.deadline_at)
        stop = cancelled or expired
        if stop and record.engine_id is None and record.engine_phase == "unclaimed":
            return view(
                await self.repo.transition(
                    owner,
                    operation_id,
                    state="failed" if expired and not cancelled else "cancelled",
                    cleanup_confirmed=True,
                    failure_reason="deadline_exceeded" if expired and not cancelled else "",
                    verification={"status": "blocked", "reason": "deadline_exceeded"}
                    if expired and not cancelled
                    else None,
                )
            )
        if record.engine_id is None:
            return view(record)
        if stop and record.state != "stopping":
            record = await self.repo.transition(
                owner,
                operation_id,
                state="stopping",
                stop_reason=record.stop_reason
                or ("cancelled" if cancelled else "deadline_exceeded"),
            )
        binding = await self.binding(owner)
        targets = [
            item["target"]
            for item in current["state"]["contract"]["criteria"]
            if item["kind"] in {"file", "read"} and item["target"]
        ]
        data = await self.request(
            owner,
            binding,
            record,
            "stop" if stop and record.supervisor else "status",
            capability,
            targets=targets,
        )
        if data["running"]:
            return view(record)
        if not data["cleanup_confirmed"]:
            if record.state != "unknown":
                record = await self.repo.transition(
                    owner, operation_id, state="unknown", engine_phase="unknown"
                )
            return view(record)
        receipt = data.get("receipt") or {}
        result = CommandResult.model_validate(receipt["result"]) if receipt.get("result") else None
        verification = verify(record.spec, result, receipt.get("verification"))
        state = (
            "completed"
            if (
                result
                and result.exit_code == 0
                and not result.timed_out
                and not result.truncated
                and verification["status"] in {"passed", "not_requested"}
            )
            else "failed"
        )
        reason = (
            ""
            if state == "completed"
            else "verification_failed"
            if result
            else "output_unavailable"
        )
        if expired:
            state, reason = "failed", "deadline_exceeded"
            verification = {**verification, "status": "blocked", "reason": reason}
        if data.get("final_revision") is None:
            state, reason = "failed", "source_revision_unavailable"
            verification = {**verification, "status": "blocked", "reason": reason}
        if cancelled or (receipt.get("cancelled") is True and not expired):
            state, reason = "cancelled", ""
        try:
            updated = await self.repo.transition(
                owner,
                operation_id,
                state=state,
                cleanup_confirmed=True,
                output_complete=result is not None and not result.truncated,
                result=result,
                final_revision=data["final_revision"],
                failure_reason=reason,
                verification=verification,
                files=data.get("files", {}),
            )
        except HarnessFailure as error:
            if error.code not in {"operation_unknown", "operation_conflict"}:
                raise
            # Another observer may have committed cleanup while this request was
            # reading output. Read that receipt; never re-finalize or unpin twice.
            committed = await self.repo.command_status(owner, operation_id)
            if committed.state not in TERMINAL_COMMAND_STATES:
                raise
            return view(committed)
        await publish_workspace_invalidation(
            self.infra.redis_client,
            thread_id=owner.thread_id,
            action="file_saved",
            revision_changed=True,
        )
        return view(updated)
