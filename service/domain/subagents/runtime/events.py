"""Existing AgentEvent projection for internal stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from service.events import AgentEvent, EventType

from .models import StageReceipt


@dataclass(frozen=True, slots=True)
class StageEventProjector:
    agent_name: str
    kind: str

    def progress(
        self,
        *,
        stage: str,
        progress: int | None = None,
        status: str = "running",
        counts: dict[str, int] | None = None,
        label: str | None = None,
    ) -> AgentEvent:
        metadata: dict[str, Any] = {
            "kind": self.kind,
            "stage": stage,
            "status": status,
        }
        if progress is not None:
            metadata["progress"] = max(0, min(100, int(progress)))
        if counts:
            metadata.update(
                {
                    str(key): max(0, int(value))
                    for key, value in counts.items()
                    if isinstance(value, int)
                }
            )
        if label:
            metadata["label"] = label[:160]
        return AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=self.agent_name,
            data=label or "",
            metadata=metadata,
        )

    def completed(self, receipt: StageReceipt, *, progress: int | None = None) -> AgentEvent:
        metadata = {"kind": self.kind, **receipt.bounded_metadata()}
        if progress is not None:
            metadata["progress"] = max(0, min(100, int(progress)))
        return AgentEvent(
            type=EventType.STATUS_UPDATE,
            agent_name=self.agent_name,
            data="",
            metadata=metadata,
        )


__all__ = ["StageEventProjector"]
