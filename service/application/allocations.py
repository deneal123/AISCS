"""Stable private allocation identity; replay never extends a sandbox deadline.

The backend owns durable generation/dispatch state. After an ambiguous create
it must use lookup, not issue another create or silently start a new generation.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from uuid import UUID

from domain.contracts import HARD_TTL_SEC
from domain.ownership import _secret


class AllocationPending(Exception):
    pass


class AllocationConflict(Exception):
    pass


class AllocationExpired(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WorkspaceAllocation:
    allocation_id: UUID
    expires_at: int

    def __post_init__(self) -> None:
        if not isinstance(self.allocation_id, UUID) or type(self.expires_at) is not int:
            raise ValueError("invalid_allocation")
        if self.expires_at <= 0:
            raise ValueError("invalid_allocation")

    def remaining(self) -> float:
        remaining = self.expires_at - time.time()
        if remaining <= 0:
            raise AllocationExpired
        if remaining > HARD_TTL_SEC:
            raise ValueError("invalid_allocation_deadline")
        return remaining

    def workspace_id(self, user_id: str) -> str:
        identity = self.allocation_id.hex + "|" + str(user_id)
        return hmac.new(
            _secret().encode(), b"workspace-allocation-v1|" + identity.encode(), hashlib.sha256
        ).hexdigest()[:32]
