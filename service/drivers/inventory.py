"""One immutable Docker inventory boundary per workspace process."""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DockerInventory:
    scope: str = "1"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.scope):
            raise ValueError("invalid workspace Docker inventory scope")

    @classmethod
    def from_environment(cls) -> "DockerInventory":
        return cls(os.environ.get("WORKSPACE_DOCKER_SCOPE", "1"))

    @property
    def label(self) -> str:
        return f"gpthub.workspace={self.scope}"
