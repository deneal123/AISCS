"""Private, run-scoped handoff of typed workflow artifacts.

Artifacts in this store are never serialized as agent events.  They let sequential
workflow stages exchange evidence and other structured values without copying them
through prompts or assistant metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


class WorkflowArtifactError(RuntimeError):
    code = "artifact_conflict"

    def __init__(self, code: str = "artifact_conflict") -> None:
        self.code = code
        super().__init__(code)


@dataclass(slots=True)
class WorkflowArtifactStore:
    """Append-only typed storage owned by one ``RunExecutionContext``."""

    _values: dict[str, Any] = field(default_factory=dict, repr=False)

    def publish(self, key: str, value: T, *, replace: bool = False) -> T:
        normalized = str(key or "").strip()
        if not normalized or len(normalized) > 96:
            raise WorkflowArtifactError("artifact_key_invalid")
        if normalized in self._values and not replace:
            raise WorkflowArtifactError()
        self._values[normalized] = value
        return value

    def get(self, key: str, expected_type: type[T]) -> T | None:
        value = self._values.get(str(key or ""))
        return value if isinstance(value, expected_type) else None

    def discard(self, key: str) -> None:
        self._values.pop(str(key or ""), None)

    def clear(self) -> None:
        self._values.clear()


__all__ = ["WorkflowArtifactError", "WorkflowArtifactStore"]
