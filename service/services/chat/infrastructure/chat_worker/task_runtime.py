"""Synchronous runtime bridge used by Celery task entrypoints."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable


def run_coroutine[Result](awaitable: Awaitable[Result]) -> Result:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(awaitable)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


__all__ = ["run_coroutine"]
