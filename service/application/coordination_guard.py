"""Fail-closed policy boundary for mutable workspace operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from infrastructure.coordinator_client import (
    CoordinationCancelled,
    CoordinationConflict,
    CoordinationDecision,
    CoordinationError,
    CoordinationForbidden,
    CoordinationPaused,
    preflight,
)


class CoordinationPayload(Protocol):
    coordination_capability: str
    coordination_fence: int | None


@dataclass(frozen=True, slots=True)
class GuardFailure(Exception):
    code: str
    status: int
    detail: str


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def coordination_required() -> bool:
    if _flag("WORKSPACE_ALLOW_UNCOORDINATED_TESTS", False):
        return False
    return _flag("WORKSPACE_COORDINATION_REQUIRED", True)


async def require_mutation(
    payload: CoordinationPayload, mutation: str, *, path: str = "", workspace_id: str = ""
) -> CoordinationDecision:
    capability = str(getattr(payload, "coordination_capability", "") or "")
    if not capability:
        if coordination_required():
            raise GuardFailure("forbidden", 403, "workspace coordination capability is required")
        return CoordinationDecision(allowed=True)
    try:
        return await preflight(
            capability,
            mutation,
            path=path,
            workspace_id=workspace_id,
            fence=getattr(payload, "coordination_fence", None),
        )
    except CoordinationPaused as exc:
        raise GuardFailure("workspace_conflict", 409, "workspace run is paused") from exc
    except CoordinationCancelled as exc:
        raise GuardFailure("workspace_conflict", 409, "workspace run is cancelled") from exc
    except CoordinationConflict as exc:
        raise GuardFailure("workspace_conflict", 409, "workspace edit lease changed") from exc
    except CoordinationForbidden as exc:
        raise GuardFailure("forbidden", 403, "workspace coordination denied") from exc
    except CoordinationError as exc:
        # The sandbox still exists; a coordinator outage is neither a driver
        # failure nor proof that its backend binding can be discarded.
        raise GuardFailure(
            "workspace_unavailable", 503, "workspace coordination is unavailable"
        ) from exc
