"""Cancellation after terminal acceptance must retain the canonical usage envelope."""

import asyncio
import json

import httpx
import pytest

from service.infrastructure.agents_client.http_agent_engine import HttpAgentEngine
from service.services.chat.infrastructure.chat_worker.execution.cancellation import run_with_cancel
from tests.test_http_agent_engine import _engine, _FakeClient, _FakeResponse, _FakeStreamCtx

RESULT = {
    "reply": "partial answer",
    "resolved_model": "synthetic",
    "total_tokens": 3,
    "per_call_usage": [{"model": "synthetic", "provider": "openai", "prompt": 2, "completion": 1}],
    "metadata": {"execution_status": "cancelled"},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", [_FakeClient, _FakeStreamCtx])
@pytest.mark.parametrize("failure", [httpx.ReadError, asyncio.CancelledError])
@pytest.mark.parametrize("terminal", ["accepted", "malformed", "missing"])
async def test_transport_context_cleanup_preserves_only_accepted_terminal(
    monkeypatch, caplog, boundary, failure, terminal
):
    calls = []

    async def fail_close(self, *exc):
        calls.append(True)
        raise failure("PRIVATE_CONTEXT_CLOSE_BODY")

    monkeypatch.setattr(boundary, "__aexit__", fail_close)
    candidate = RESULT if terminal == "accepted" else {"reply": 123}
    lines = [] if terminal == "missing" else [json.dumps({"__result__": candidate})]
    engine, _ = _engine(monkeypatch, lines)
    events = []
    if terminal == "accepted":
        assert (
            await engine.execute(text="synthetic", thread_id="thread", on_event=events.append)
            == RESULT
        )
        assert len(events) == 1
        assert events[0].metadata["run_integrity"]["reasons"] == ["error_after_result"]
    else:
        with pytest.raises(failure):
            await engine.execute(text="synthetic", thread_id="thread", on_event=events.append)
    assert calls == [True]
    assert "PRIVATE_CONTEXT_CLOSE_BODY" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "cancel"])
async def test_accepted_result_survives_reader_interrupt(monkeypatch, failure, caplog):
    async def interrupted_lines(self):
        yield json.dumps({"__result__": RESULT})
        if failure == "transport":
            raise httpx.ReadError("private-provider-body-marker")
        raise asyncio.CancelledError()

    monkeypatch.setattr(_FakeResponse, "aiter_lines", interrupted_lines)
    engine, _ = _engine(monkeypatch, [])
    result = await engine.execute(text="synthetic", thread_id="thread")
    assert result == RESULT
    assert "private-provider-body-marker" not in caplog.text


@pytest.mark.asyncio
async def test_cooperative_cancel_keeps_result_returned_during_execution_cleanup():
    started = asyncio.Event()

    class Redis:
        def get(self, key):
            return "1" if started.is_set() else None

        def delete(self, key):
            return 1

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # The HTTP reader had latched a valid terminal before interruption.
            return RESULT

    result = await run_with_cancel(
        work(), redis_client=Redis(), celery_task_id="task", poll_interval=0.001
    )
    assert result == RESULT


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "cancel"])
async def test_reader_interrupt_without_valid_result_is_not_billable(monkeypatch, failure):
    async def interrupted_lines(self):
        yield json.dumps({"__result__": {"reply": 123, "per_call_usage": "invalid"}})
        if failure == "transport":
            raise httpx.ReadError("private-transport-marker")
        raise asyncio.CancelledError()

    monkeypatch.setattr(_FakeResponse, "aiter_lines", interrupted_lines)
    engine, _ = _engine(monkeypatch, [])
    expected = httpx.ReadError if failure == "transport" else asyncio.CancelledError
    with pytest.raises(expected):
        await engine.execute(text="synthetic", thread_id="thread")


@pytest.mark.asyncio
async def test_real_httpx_parser_keeps_terminal_and_closes_interrupted_stream(monkeypatch):
    from types import SimpleNamespace

    from service.infrastructure.agents_client import http_agent_engine as transport_module

    closed = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (json.dumps({"__result__": RESULT}) + "\n").encode()
            raise httpx.ReadError("private-body-marker")

        async def aclose(self):
            closed.append(True)

    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))
    monkeypatch.setattr(
        transport_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=transport, **kwargs),
    )
    engine = HttpAgentEngine(SimpleNamespace(agents=SimpleNamespace(sidecar_url="http://agents")))
    assert await engine.execute(text="synthetic", thread_id="thread") == RESULT
    assert closed == [True]


@pytest.mark.asyncio
async def test_actual_local_http_disconnect_after_terminal_keeps_usage():
    from types import SimpleNamespace

    handlers = []

    async def serve(reader, writer):
        task = asyncio.current_task()
        handlers.append(task)
        try:
            await reader.readuntil(b"\r\n\r\n")
            body = (json.dumps({"__result__": RESULT}) + "\n").encode()
            writer.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
            writer.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
            await writer.drain()
            # Deliberately close without the final zero chunk, after receipt.
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        engine = HttpAgentEngine(
            SimpleNamespace(agents=SimpleNamespace(sidecar_url=f"http://127.0.0.1:{port}"))
        )
        result = await asyncio.wait_for(
            engine.execute(text="synthetic", thread_id="thread"), timeout=10
        )
        assert result == RESULT
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers)
