"""Storage resource cleanup; no external network or provider calls."""

import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest
import urllib3

from service.infrastructure.storage.minio_file_storage import MinioFileStorage


def storage(response):
    adapter = object.__new__(MinioFileStorage)
    adapter._bucket = "fixture-bucket"
    adapter._client = Mock()
    adapter._client.get_object.return_value = response
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("head", [False, True], ids=["whole", "head"])
async def test_connection_is_released_even_when_response_close_fails(head):
    response = Mock()
    response.read.return_value = b"fixture"
    response.close.side_effect = OSError("private-close-marker")
    adapter = storage(response)

    with pytest.raises(OSError):
        if head:
            await adapter.get_file_head("fixture-key", 16)
        else:
            await adapter.get_file("fixture-key")

    response.release_conn.assert_called_once_with()
    adapter._client.get_object.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("head", [False, True], ids=["whole", "head"])
async def test_cancelled_caller_does_not_repeat_read_and_worker_releases_response(head):
    entered = threading.Event()
    proceed = threading.Event()
    closed = threading.Event()
    released = threading.Event()
    response = Mock()

    def read(amount=None):
        entered.set()
        assert proceed.wait(5), "fixture_read_not_released"
        return b"fixture"[:amount]

    response.read.side_effect = read
    response.close.side_effect = closed.set
    response.release_conn.side_effect = released.set
    adapter = storage(response)
    call = adapter.get_file_head("fixture-key", 16) if head else adapter.get_file("fixture-key")
    task = asyncio.create_task(call)
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        proceed.set()
        assert await asyncio.to_thread(released.wait, 3)
        assert closed.is_set()
        adapter._client.get_object.assert_called_once()
        response.close.assert_called_once_with()
        response.release_conn.assert_called_once_with()
    finally:
        proceed.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("head", [False, True], ids=["whole", "head"])
async def test_close_failure_does_not_exhaust_a_real_http_connection_pool(head):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "7")
            self.end_headers()
            self.wfile.write(b"fixture")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    pool = urllib3.PoolManager(maxsize=1, block=True, retries=False)
    endpoint = f"http://127.0.0.1:{server.server_port}/fixture"
    adapter = storage(None)

    def get_object(*_args, **_kwargs):
        response = pool.request("GET", endpoint, preload_content=False, pool_timeout=1, timeout=2)
        original_close = response.close

        def close():
            original_close()
            raise OSError("private-close-marker")

        response.close = close
        return response

    adapter._client.get_object.side_effect = get_object
    try:
        with pytest.raises(OSError, match="private-close-marker"):
            if head:
                await adapter.get_file_head("fixture-key", 7)
            else:
                await adapter.get_file("fixture-key")
        # The next consumer must obtain the single pool slot, not time out.
        response = await asyncio.to_thread(pool.request, "GET", endpoint, pool_timeout=1, timeout=2)
        assert response.data == b"fixture"
        response.close()
        response.release_conn()
    finally:
        pool.clear()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        serving.join(timeout=3)
