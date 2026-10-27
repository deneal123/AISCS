"""Closed command recipes and durable state, never model-issued authority."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from service.services.chat.domain.ide.console import CommandResult
from service.services.chat.domain.ide.files import IdeReadError, validate_path
from service.shared.ide_command import CommandSpec as CommandRecipe

ACTIVE_COMMAND_STATES = (
    "preparing",
    "ready",
    "dispatching",
    "running",
    "stopping",
    "unknown",
)
TERMINAL_COMMAND_STATES = ("completed", "failed", "cancelled")
CommandState = Literal[
    "preparing",
    "ready",
    "dispatching",
    "running",
    "stopping",
    "unknown",
    "completed",
    "failed",
    "cancelled",
]


class CommandSpec(CommandRecipe):
    @model_validator(mode="after")
    def path_policy(self):
        if self.target is not None:
            try:
                validate_path(self.target)
            except IdeReadError:
                raise ValueError("invalid_command_recipe") from None
        return self


class CommandRecord(BaseModel):
    """Private executor state; publication must project safe fields explicitly."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    operation_id: UUID
    task_id: UUID
    repository_id: UUID
    workspace_id: str = Field(min_length=1, max_length=128)
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    attempt_id: UUID
    epoch: int = Field(ge=1)
    deadline_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    spec: CommandSpec = Field(repr=False)
    state: CommandState = "preparing"
    snapshot_id: UUID | None = None
    snapshot_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_revision: str | None = Field(default=None, min_length=1, max_length=128)
    final_revision: str | None = Field(default=None, min_length=1, max_length=128)
    engine_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    container_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$", repr=False)
    result: CommandResult | None = Field(default=None, repr=False)
    cleanup_confirmed: bool = Field(default=False, strict=True)
    output_complete: bool = Field(default=False, strict=True)
    dispatch_authorized: bool = Field(default=False, strict=True)
    stop_reason: Literal["cancelled", "deadline_exceeded"] | None = None
    engine_phase: Literal[
        "unclaimed", "creating", "created", "handshaking", "waiting", "sent", "unknown"
    ] = "unclaimed"
    supervisor: dict | None = Field(default=None, repr=False)
    verification: dict | None = Field(default=None, repr=False)
    failure_reason: Literal[
        "",
        "output_unavailable",
        "runtime_unavailable",
        "verification_failed",
        "source_revision_unavailable",
        "deadline_exceeded",
        "preparation_failed",
        "binding_changed",
    ] = ""

    @model_validator(mode="after")
    def coherent(self):
        preflight_failed = (
            self.state == "failed"
            and self.failure_reason in {"preparation_failed", "deadline_exceeded"}
            and self.engine_id is None
            and self.engine_phase == "unclaimed"
        )
        if (self.snapshot_id is None) != (self.snapshot_digest is None):
            raise ValueError("command_snapshot_missing")
        if (self.engine_id is None) != (self.container_id is None):
            raise ValueError("command_process_missing")
        if not preflight_failed and self.state in {
            "ready",
            "dispatching",
            "running",
            "stopping",
            "completed",
            "failed",
        }:
            if self.snapshot_id is None or not self.source_revision:
                raise ValueError("command_snapshot_missing")
        if not preflight_failed and self.state in {
            "dispatching",
            "running",
            "stopping",
            "completed",
            "failed",
        }:
            if self.engine_id is None:
                raise ValueError("command_process_missing")
        if self.state in {"completed", "failed"} and (
            (
                self.result is None
                and self.failure_reason
                not in {
                    "output_unavailable",
                    "source_revision_unavailable",
                    "deadline_exceeded",
                    "preparation_failed",
                    "binding_changed",
                }
            )
            or not self.cleanup_confirmed
            or (
                not self.final_revision
                and not preflight_failed
                and self.failure_reason
                not in {"source_revision_unavailable", "preparation_failed", "binding_changed"}
            )
        ):
            raise ValueError("command_result_unconfirmed")
        if self.state == "completed" and (
            self.result is None
            or self.result.exit_code != 0
            or self.result.timed_out
            or not self.output_complete
            or self.result.truncated
        ):
            raise ValueError("command_result_unconfirmed")
        if (
            self.state == "failed"
            and self.result is not None
            and self.result.exit_code == 0
            and not self.result.timed_out
            and self.output_complete
            and not self.result.truncated
            and self.failure_reason
            not in {
                "verification_failed",
                "source_revision_unavailable",
                "deadline_exceeded",
                "binding_changed",
            }
        ):
            raise ValueError("command_result_unconfirmed")
        if self.state == "cancelled" and self.engine_id and not self.cleanup_confirmed:
            raise ValueError("command_cleanup_unconfirmed")
        if self.supervisor is not None:
            if (
                set(self.supervisor) != {"pid", "start_time", "version"}
                or type(self.supervisor["pid"]) is not int
                or self.supervisor["pid"] <= 1
                or type(self.supervisor["version"]) is not int
                or self.supervisor["version"] != 1
                or not isinstance(self.supervisor["start_time"], str)
                or not self.supervisor["start_time"].isdigit()
            ):
                raise ValueError("command_identity_invalid")
        return self

    def advance(self, **updates):
        return CommandRecord.model_validate({**self.model_dump(), **updates})
