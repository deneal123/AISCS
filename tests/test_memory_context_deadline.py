import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from service.services.analytics.application.memory.service import MemoryService
from service.services.chat.infrastructure.agent_context import load_memory_parts
from service.settings import config


@pytest.mark.asyncio
async def test_unavailable_recall_does_not_delay_or_discard_available_facts(monkeypatch):
    monkeypatch.setattr(config.agents, "memory_context_timeout_sec", 0.1)
    cancelled = asyncio.Event()

    async def recall(*_args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(MemoryService, "get_memory_context", AsyncMock(return_value="owned facts"))
    monkeypatch.setattr(MemoryService, "recall_semantic", recall)
    result = await asyncio.wait_for(
        load_memory_parts("synthetic-user", logging.getLogger(__name__), "query"), timeout=1
    )
    assert result == ("owned facts", "")
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_cancelling_request_cancels_both_memory_reads(monkeypatch):
    entered = [asyncio.Event(), asyncio.Event()]
    cancelled = [False, False]

    def read(index):
        async def wait(*_args, **_kwargs):
            entered[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled[index] = True

        return wait

    monkeypatch.setattr(MemoryService, "get_memory_context", read(0))
    monkeypatch.setattr(MemoryService, "recall_semantic", read(1))
    task = asyncio.create_task(
        load_memory_parts("synthetic-user", logging.getLogger(__name__), "query")
    )
    await asyncio.gather(*(event.wait() for event in entered))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled == [True, True]
