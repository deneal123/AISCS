"""Closed, private command protocol; no command/output enters Chat or telemetry."""

import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConsoleError(Exception):
    def __init__(self, code="ide_console_unavailable"):
        self.code = code
        super().__init__(code)


class CommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: UUID
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    command: str = Field(min_length=1, max_length=8192, strict=True)

    @model_validator(mode="after")
    def command_bytes(self):
        if (
            not self.execution_id.int
            or not self.command.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in self.command)
        ):
            raise ValueError("invalid_command")
        return self


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    exit_code: int
    stdout: str = Field(max_length=20000)
    stderr: str = Field(max_length=20000)
    truncated: bool
    duration_sec: float = Field(ge=0)
    timed_out: bool

    @model_validator(mode="after")
    def finite_duration(self):
        if not math.isfinite(self.duration_sec):
            raise ValueError("invalid_duration")
        return self


class CommandReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    execution_id: UUID
    repository_id: UUID
    generation: str = Field(pattern=r"^[a-f0-9]{64}$")
    state: Literal["dispatching", "completed", "unknown"]
    result: CommandResult | None = None

    @model_validator(mode="after")
    def result_state(self):
        if (self.state == "completed") != (self.result is not None):
            raise ValueError("invalid_command_receipt")
        return self
