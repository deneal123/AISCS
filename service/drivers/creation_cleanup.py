"""Bounded retirement of acknowledged containers before lifecycle ownership transfer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from drivers.base import ContainerRef


async def _remove_owned(
    ref: ContainerRef, destroy: Callable[[ContainerRef], Awaitable[None]]
) -> bool:
    try:
        await asyncio.wait_for(destroy(ref), timeout=65.0)
    except (Exception, asyncio.CancelledError):
        # Do not leak a private exception through an unobserved child task.
        return False
    return True


async def settle_creation(
    ref: ContainerRef, destroy: Callable[[ContainerRef], Awaitable[None]]
) -> tuple[ContainerRef | None, bool]:
    """Return cleanup debt and whether cancellation occurred during retirement."""
    cleanup = asyncio.create_task(_remove_owned(ref, destroy))
    interrupted = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            interrupted = True
    removed = not cleanup.cancelled() and cleanup.result()
    return (None if removed else ref), interrupted
