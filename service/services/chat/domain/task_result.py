"""Closed public projection of a harness stop; no transcript or capability fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from service.shared.task_contract import TaskResultV2


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    status: Literal["partial", "cancelled"]
    blocker: Literal[
        "no_progress",
        "prompt_budget",
        "round_limit",
        "unconfirmed_effect",
        "cancelled",
        "tool_failed",
        "verification_failed",
    ]
    rounds: int = Field(ge=0, le=1024)
    repair_cycles: int = Field(ge=0, le=2)
    verified: Literal[False]


def parse_task_result(value) -> dict:
    codec = (
        TaskResultV2 if isinstance(value, dict) and value.get("schema_version") == 2 else TaskResult
    )
    return codec.model_validate(value).model_dump(mode="json")
