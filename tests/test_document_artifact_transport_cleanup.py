"""Every private artifact HTTP client retains one deterministic close owner."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from service.infrastructure import workspace_client, workspace_documents


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_cancelled_artifact_request_closes_client_before_propagating(
    monkeypatch, cleanup_fails
):
    client = SimpleNamespace(
        build_request=lambda *_args, **_kwargs: object(),
        send=AsyncMock(side_effect=asyncio.CancelledError()),
        aclose=AsyncMock(side_effect=RuntimeError("private-marker") if cleanup_fails else None),
    )
    monkeypatch.setattr(workspace_documents.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 10, "private-key", None)
    )
    with pytest.raises(asyncio.CancelledError):
        await workspace_documents.stream_document_artifact(
            {"workspace_id": "fixture", "user_id": "owner", "token": "private"},
            build_id="build",
            artifact_id="artifact",
        )
    client.send.assert_awaited_once()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_actual_http_client_is_closed_on_header_wait_cancellation(monkeypatch):
    entered, disconnected = asyncio.Event(), asyncio.Event()
    clients = []
    real_client = httpx.AsyncClient

    async def handler(reader, writer):
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            await reader.readexactly(length)
            entered.set()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
            disconnected.set()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    def create_client(**options):
        assert options.get("trust_env") is False
        assert options.get("follow_redirects") is False
        client = real_client(**options)
        clients.append(client)
        return client

    monkeypatch.setattr(workspace_documents.httpx, "AsyncClient", create_client)
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, f"http://127.0.0.1:{port}", 10, "", None)
    )
    request = asyncio.create_task(
        workspace_documents.stream_document_artifact(
            {"workspace_id": "fixture"},
            build_id="build",
            artifact_id="artifact",
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(disconnected.wait(), 5)
        assert len(clients) == 1 and clients[0].is_closed
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        for client in clients:
            await client.aclose()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_response_close_failure_does_not_leak_owned_client():
    response = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("private-marker")))
    client = SimpleNamespace(aclose=AsyncMock())
    artifact = workspace_documents.DocumentArtifactDownload(
        client,
        response,
        "file.pdf",
        "application/pdf",
        1,
        "a" * 64,
    )
    with pytest.raises(RuntimeError):
        await artifact.close()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 503, 200])
async def test_rejected_response_close_failure_does_not_leak_client(monkeypatch, status):
    response = SimpleNamespace(
        status_code=status, headers={}, aclose=AsyncMock(side_effect=RuntimeError("private-marker"))
    )
    client = SimpleNamespace(
        build_request=lambda *_args, **_kwargs: object(),
        send=AsyncMock(return_value=response),
        aclose=AsyncMock(),
    )
    monkeypatch.setattr(workspace_documents.httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(
        workspace_client, "_config", lambda: (True, "http://workspace", 10, "private-key", None)
    )
    with pytest.raises(RuntimeError):
        await workspace_documents.stream_document_artifact(
            {"workspace_id": "fixture"},
            build_id="build",
            artifact_id="artifact",
        )
    response.aclose.assert_awaited_once()
    client.aclose.assert_awaited_once()
