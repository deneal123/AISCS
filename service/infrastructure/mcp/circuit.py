"""Bounded process-local circuit breaker for admin-declared MCP servers."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic


@dataclass(slots=True)
class _State:
    failures: int = 0
    open_until: float = 0.0


class McpCircuitBreaker:
    """A small in-process breaker; it never stores request or server URL data."""

    def __init__(self) -> None:
        self._states: dict[str, _State] = {}
        self._lock = Lock()

    def open(self, server_id: str) -> bool:
        with self._lock:
            state = self._states.get(server_id)
            return bool(state and state.open_until > monotonic())

    def failed(self, server_id: str, *, threshold: int, cooldown_sec: float) -> bool:
        with self._lock:
            state = self._states.setdefault(server_id, _State())
            state.failures += 1
            if state.failures >= max(1, threshold):
                state.open_until = monotonic() + max(1.0, cooldown_sec)
                return True
            return False

    def succeeded(self, server_id: str) -> None:
        with self._lock:
            self._states.pop(server_id, None)

    def reset(self) -> None:
        """Test-only reset; production state naturally expires after cooldown."""
        with self._lock:
            self._states.clear()


circuit_breaker = McpCircuitBreaker()
