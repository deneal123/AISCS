"""Bounded process-local capability registry counters.

The agents sidecar currently exposes operational aggregates through its existing health
surface. Keeping the counter here makes labels closed and lets the platform Prometheus
projection consume them without introducing a second metrics endpoint.
"""

from __future__ import annotations

from collections import Counter
from threading import Lock

METRIC_NAME = "agent_capability_registry_total"
STAGES = frozenset({"compile", "startup", "run", "mcp_admission", "build"})
STATUSES = frozenset({"ok", "failed", "rejected"})
REASONS = frozenset(
    {
        "none",
        "import_failed",
        "invalid_spec",
        "duplicate_name",
        "reference_missing",
        "settings_field_missing",
        "tool_name_mismatch",
        "billing_mismatch",
        "native_collision",
        "capability_build",
    }
)

_COUNTS: Counter[tuple[str, str, str]] = Counter()
_LOCK = Lock()


def record(stage: str, status: str, reason: str = "none") -> None:
    bounded = (
        stage if stage in STAGES else "run",
        status if status in STATUSES else "failed",
        reason if reason in REASONS else "invalid_spec",
    )
    with _LOCK:
        _COUNTS[bounded] += 1


def snapshot() -> tuple[dict[str, object], ...]:
    with _LOCK:
        values = tuple(sorted(_COUNTS.items()))
    return tuple(
        {"stage": stage, "status": status, "reason": reason, "count": count}
        for (stage, status, reason), count in values
    )


def prometheus_samples() -> tuple[tuple[str, dict[str, str], int], ...]:
    """Return dependency-free samples for the platform metrics collector."""

    return tuple(
        (
            METRIC_NAME,
            {
                "stage": str(item["stage"]),
                "status": str(item["status"]),
                "reason": str(item["reason"]),
            },
            int(item["count"]),
        )
        for item in snapshot()
    )


def reset_for_tests() -> None:
    with _LOCK:
        _COUNTS.clear()


__all__ = [
    "METRIC_NAME",
    "REASONS",
    "STAGES",
    "STATUSES",
    "prometheus_samples",
    "record",
    "reset_for_tests",
    "snapshot",
]
