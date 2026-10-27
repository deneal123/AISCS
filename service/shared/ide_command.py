"""Portable command recipe contract; sandbox path policy remains executor-owned."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    profile: Literal["shell", "python_script", "unittest", "pytest"]
    target: str | None = Field(default=None, min_length=1, max_length=1024)
    command: str | None = Field(default=None, min_length=1, max_length=8192, repr=False)
    expected_stdout: str | None = Field(default=None, max_length=4096, repr=False)
    timeout_sec: int = Field(default=60, ge=1, le=120)
    criterion_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @model_validator(mode="after")
    def recipe(self):
        if self.profile == "shell":
            if (
                self.target is not None
                or not self.command
                or not self.command.strip()
                or self.expected_stdout is not None
            ):
                raise ValueError("invalid_command_recipe")
            if any(ord(char) < 32 or ord(char) == 127 for char in self.command):
                raise ValueError("invalid_command_recipe")
        elif self.command is not None or self.target is None:
            raise ValueError("invalid_command_recipe")
        if self.target is not None and self.profile == "python_script":
            if not self.target.endswith(".py"):
                raise ValueError("invalid_command_recipe")
        return self
