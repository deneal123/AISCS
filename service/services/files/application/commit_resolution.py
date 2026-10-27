"""Bounded settlement of storage ownership after a cancelled metadata commit."""

import asyncio
import logging
from collections.abc import Awaitable

logger = logging.getLogger(__name__)


async def settle_cancelled_metadata(resolution: Awaitable[object]) -> None:
    """Drain one exact-key resolution; preserve cancellation as the caller's outcome.

    A committed row retains its object. Proven rollback compensates it. An
    unavailable lookup preserves the object because absence is not established.
    Repeated disconnects cannot interrupt this decision, but the settlement has
    a fixed deadline and never changes a cancellation into an upload success.
    """

    async def bounded() -> None:
        try:
            async with asyncio.timeout(30):
                await resolution
        except Exception:
            logger.warning(
                "cancelled file metadata unresolved",
                extra={"component": "file_library", "failure_code": "unavailable"},
            )

    task = asyncio.create_task(bounded())
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    # Consume every terminal outcome without exposing exception text or changing
    # the original cancellation. No automatic metadata-write retry is performed.
    if not task.cancelled():
        task.result()
