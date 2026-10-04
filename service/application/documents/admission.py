"""Run-local reservations for preparation, live compilers and cleanup debt."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from .projects import DocumentProjectError


class BuildAdmission:
    def __init__(
        self,
        limit: int,
        occupied: Callable[[], int],
        *,
        observed: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        self.limit = limit
        self.occupied = occupied
        self.observed = observed
        self.preparing = 0
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def reserve(self):
        async with self._lock:
            try:
                occupied = await self.observed() if self.observed else self.occupied()
            except Exception:
                raise DocumentProjectError("runtime_unavailable") from None
            if self.preparing + occupied >= self.limit:
                raise DocumentProjectError("runtime_unavailable")
            self.preparing += 1
        try:
            yield
        finally:
            async with self._lock:
                self.preparing -= 1
