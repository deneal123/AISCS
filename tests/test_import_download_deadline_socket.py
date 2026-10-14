"""Absolute fetch deadlines over real loopback sockets, without external services."""

import asyncio

import httpx
import pytest
from application import importer


@pytest.mark.parametrize("slow", [False, True])
async def test_socket_body_deadline_closes_connection(monkeypatch, slow):
    original = httpx.AsyncClient
    disconnected = asyncio.Event()
    tasks = set()
    sent = 0

    async def public(_host):
        # Test-boundary allowance only; production SSRF checks remain enabled.
        return None

    async def serve(reader, writer):
        nonlocal sent
        task = asyncio.current_task()
        tasks.add(task)
        watcher = None
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
            await writer.drain()
            watcher = asyncio.create_task(reader.read())
            for _ in range(100):
                if watcher.done():
                    break
                writer.write(b"x")
                await writer.drain()
                sent += 1
                if slow:
                    await asyncio.sleep(0.02)
            await watcher
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if watcher and not watcher.done():
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            tasks.discard(task)
            disconnected.set()

    monkeypatch.setattr(importer, "assert_public_host", public)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(trust_env=False, **kw))
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with server:
            url = f"http://127.0.0.1:{port}/fixture"
            if slow:
                with pytest.raises(importer.ImportRefused, match="temporarily unavailable"):
                    await asyncio.wait_for(importer.fetch(url, timeout_sec=0.4), 3)
                assert 0 < sent < 100
            else:
                assert await asyncio.wait_for(importer.fetch(url, timeout_sec=2), 3) == b"x" * 100
            await asyncio.wait_for(disconnected.wait(), 2)
            assert not tasks
    finally:
        server.close()
        await server.wait_closed()
        pending = list(tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
