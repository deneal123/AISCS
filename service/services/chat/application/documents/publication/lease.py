"""Bounded ownership checkpoints for long-running document delivery."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from service.services.chat.persistence.documents import publication as document_publications

_RENEW_TIMEOUT = 5
_HEARTBEAT_INTERVAL = 40


class PublicationLeaseLost(RuntimeError):
    def __init__(self):
        super().__init__("publication_lease_lost")


async def require_publication_lease(pg_connector: Any, row: dict, lost: asyncio.Event) -> None:
    """Revalidate the exact live token before new work or Library publication."""
    if lost.is_set():
        raise PublicationLeaseLost()
    try:
        async with asyncio.timeout(_RENEW_TIMEOUT):
            async with pg_connector.get_session_context() as session:
                owned = await document_publications.renew(
                    session,
                    job_id=uuid.UUID(str(row["id"])),
                    lease_token=uuid.UUID(str(row["lease_token"])),
                )
                await session.commit()
        if owned and not lost.is_set():
            return
    except Exception:
        # Neither a failed query nor a lost acknowledgement proves ownership.
        pass
    lost.set()
    raise PublicationLeaseLost() from None


@asynccontextmanager
async def renewing_publication_lease(pg_connector: Any, row: dict):
    """Check ownership immediately, then renew without exposing row details."""
    lost = asyncio.Event()
    try:
        await require_publication_lease(pg_connector, row, lost)
    except PublicationLeaseLost:
        yield lost
        return

    async def heartbeat() -> None:
        while not lost.is_set():
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            try:
                await require_publication_lease(pg_connector, row, lost)
            except PublicationLeaseLost:
                return

    task = asyncio.create_task(heartbeat())
    try:
        yield lost
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def lease_checked_chunks(
    chunks: AsyncIterator[bytes], lost: asyncio.Event
) -> AsyncGenerator[bytes]:
    """Interrupt even a blocked download, not an in-flight storage/DB commit."""
    iterator = aiter(chunks)
    loss = asyncio.create_task(lost.wait())
    try:
        while True:
            if lost.is_set():
                raise PublicationLeaseLost()
            pending = asyncio.ensure_future(anext(iterator))
            try:
                await asyncio.wait((pending, loss), return_when=asyncio.FIRST_COMPLETED)
                if lost.is_set():
                    raise PublicationLeaseLost()
                try:
                    chunk = pending.result()
                except StopAsyncIteration:
                    return
            finally:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            yield chunk
    finally:
        loss.cancel()
        await asyncio.gather(loss, return_exceptions=True)
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()
