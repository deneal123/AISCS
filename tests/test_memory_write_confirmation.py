"""Отказ и потерянный ACK не должны становиться подтверждённой записью."""

from unittest.mock import AsyncMock

import httpx
import pytest

from service.infrastructure.memory.memos import MemOSMemoryIntegration
from service.services.chat.infrastructure.context.projection import project_summary
from service.shared.memory_outcomes import MemoryWriteResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,payload,expected",
    [
        (200, {"code": 200, "data": [{"id": "x", "indexed": True}]}, MemoryWriteResult.CONFIRMED),
        (200, {"code": 200, "data": [{"id": "x"}]}, MemoryWriteResult.UNKNOWN),
        (200, {"code": 500}, MemoryWriteResult.UNKNOWN),
        (200, {"code": 200, "data": []}, MemoryWriteResult.UNKNOWN),
        (503, {}, MemoryWriteResult.UNKNOWN),
        (422, {}, MemoryWriteResult.REJECTED),
    ],
)
async def test_write_requires_positive_memory_receipt(status, payload, expected):
    adapter = MemOSMemoryIntegration(
        base_url="http://memos",
        async_mode="sync",
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=payload)),
    )
    assert (
        await adapter.save_messages(
            user_id="u",
            messages=[{"role": "user", "content": "Факт"}],
        )
        is expected
    )


@pytest.mark.asyncio
async def test_unknown_projection_not_repeated_or_marked_success(monkeypatch):
    values = {}

    class Redis:
        def set(self, key, value, nx=False):
            if nx and key in values:
                return False
            values[key] = value
            return True

        def get(self, key):
            return values.get(key)

    write = AsyncMock(return_value=MemoryWriteResult.UNKNOWN)
    monkeypatch.setattr(
        "service.services.chat.infrastructure.context.projection.MemoryService",
        lambda: type("Service", (), {"remember_conversation": staticmethod(write)})(),
    )
    args = dict(client=Redis(), thread_id="t", user_id="u", summary="Резюме")
    assert await project_summary(**args) == "unknown"
    assert await project_summary(**args) == "unknown"
    assert write.await_count == 1
    assert set(values.values()) == {"unknown"}
