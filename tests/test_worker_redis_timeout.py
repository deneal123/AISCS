"""Worker Redis reads have socket bounds, without automatic command retry."""

import asyncio
from types import SimpleNamespace

import pytest

from service.services.chat.infrastructure.chat_worker import factory
from service.services.chat.infrastructure.chat_worker.execution.cancellation import (
    CancelledByUser,
    run_with_cancel,
)


def _config(port=0):
    return SimpleNamespace(
        redis=SimpleNamespace(
            enabled=True,
            host="127.0.0.1",
            port=port,
            db=0,
            password="",
        )
    )


def test_worker_redis_factory_sets_read_and_connect_timeouts():
    client = factory.ChatWorkerDependencyFactory().create_redis_client(_config())
    try:
        kwargs = client.connection_pool.connection_kwargs
        assert kwargs["socket_timeout"] == 2.0
        assert kwargs["socket_connect_timeout"] == 2.0
        assert kwargs["retry_on_error"] == []
    finally:
        client.close()


@pytest.mark.asyncio
async def test_real_redis_client_recovers_after_stalled_tcp_read(monkeypatch):
    monkeypatch.setattr(factory, "_WORKER_REDIS_TIMEOUT_SEC", 0.03, raising=False)
    handlers = []
    writers = []
    reads = 0
    stalled_closed = asyncio.Event()

    async def serve(reader, writer):
        nonlocal reads
        handlers.append(asyncio.current_task())
        writers.append(writer)
        try:
            while line := await reader.readline():
                assert line.startswith(b"*")
                parts = []
                for _ in range(int(line[1:])):
                    length = await reader.readline()
                    assert length.startswith(b"$")
                    parts.append(await reader.readexactly(int(length[1:])))
                    assert await reader.readexactly(2) == b"\r\n"
                if parts[0] == b"GET":
                    reads += 1
                    if reads == 1:
                        assert await reader.read() == b""
                        stalled_closed.set()
                        return
                    writer.write(b"$1\r\n1\r\n")
                elif parts[0] == b"DEL":
                    writer.write(b":1\r\n")
                else:
                    writer.write(b"+OK\r\n")
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    client = factory.ChatWorkerDependencyFactory().create_redis_client(
        _config(server.sockets[0].getsockname()[1])
    )

    async def work():
        await asyncio.Event().wait()

    try:
        assert client.connection_pool.connection_kwargs["socket_timeout"] == 0.03
        with pytest.raises(CancelledByUser):
            await asyncio.wait_for(
                run_with_cancel(
                    work(), redis_client=client, celery_task_id="synthetic", poll_interval=0.001
                ),
                timeout=2,
            )
        await asyncio.wait_for(stalled_closed.wait(), timeout=1)
        assert reads == 2
    finally:
        await asyncio.to_thread(client.close)
        server.close()
        await server.wait_closed()
        for writer in writers:
            writer.close()
        await asyncio.gather(*handlers)
