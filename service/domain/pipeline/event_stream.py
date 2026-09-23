"""Helpers for sequencing and emitting agent events."""

from __future__ import annotations

from service.events import AgentEvent


class EventSequencer:
    """Assign monotonic sequence numbers to AgentEvent instances."""

    def __init__(self) -> None:
        self._seq = 0

    def attach(self, event: AgentEvent) -> AgentEvent:
        """Attach next seq number to an existing event and return it."""
        self._seq += 1
        event.seq = self._seq
        return event
