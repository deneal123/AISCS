"""Unhandled HTTP failures cannot escape to the server with private bodies."""

import asyncio
import logging
import traceback

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.responses import StreamingResponse

from service.shared.presentation.handlers.exceptions_handlers import setup_exception_handlers
from service.shared.presentation.handlers.http_failure_boundary import (
    HttpFailureBoundary,
    HttpResponseAborted,
)

MARKER = "PRIVATE_UNHANDLED_HTTP_EXCEPTION_MARKER"


def app_fixture(*, debug=False):
    app = FastAPI(debug=debug)
    setup_exception_handlers(app)

    @app.get("/fail")
    async def fail(private: str):
        raise RuntimeError(private)

    @app.get("/known")
    async def known():
        raise HTTPException(409, "Conflict")

    @app.get("/stream")
    async def stream(private: str):
        async def chunks():
            yield b"first"
            raise RuntimeError(private)

        return StreamingResponse(chunks())

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True])
async def test_unhandled_error_is_safe_response_without_framework_reraise(debug):
    async with AsyncClient(
        transport=ASGITransport(app=app_fixture(debug=debug)), base_url="http://fixture"
    ) as client:
        response = await client.get("/fail", params={"private": MARKER})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert MARKER not in response.text


@pytest.mark.asyncio
async def test_started_stream_aborts_with_safe_cause_not_fabricated_completion():
    app = app_fixture()
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "method": "GET",
        "scheme": "http",
        "path": "/stream",
        "query_string": ("private=" + MARKER).encode(),
        "headers": [],
        "server": ("fixture", 80),
        "client": ("127.0.0.1", 1),
    }
    with pytest.raises(RuntimeError) as caught:
        await app(scope, receive, send)
    assert MARKER not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__suppress_context__
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"first"
    assert messages[1]["more_body"]
    assert not any(
        message["type"] == "http.response.body" and not message.get("more_body", False)
        for message in messages
    )


@pytest.mark.asyncio
async def test_known_http_response_remains_legacy_contract():
    async with AsyncClient(
        transport=ASGITransport(app=app_fixture()), base_url="http://fixture"
    ) as client:
        response = await client.get("/known")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Conflict"


@pytest.mark.asyncio
async def test_cancellation_is_not_converted_into_500():
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/cancel")
    async def cancel():
        raise asyncio.CancelledError()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://fixture") as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get("/cancel")


@pytest.mark.asyncio
async def test_completed_response_background_failure_is_bounded(monkeypatch, caplog):
    from starlette.background import BackgroundTask
    from starlette.responses import PlainTextResponse

    from service.shared.presentation.handlers import exceptions_handlers as handlers

    monkeypatch.setattr(handlers.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(handlers.logger, "propagate", False)
    monkeypatch.setattr(handlers.logger, "disabled", False)
    monkeypatch.setattr(handlers.logger, "level", logging.DEBUG)
    app = FastAPI()
    setup_exception_handlers(app)

    async def background():
        raise RuntimeError(MARKER)

    @app.get("/background")
    async def completed():
        return PlainTextResponse("sent", background=BackgroundTask(background))

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://fixture"
    ) as client:
        response = await client.get("/background")
    assert response.status_code == 200
    assert response.text == "sent"
    assert caplog.records
    assert all(record.exc_info is None for record in caplog.records)
    assert MARKER not in caplog.text


@pytest.mark.asyncio
async def test_boundary_does_not_read_or_buffer_successful_stream():
    sends = []
    receives = 0

    async def receive():
        nonlocal receives
        receives += 1
        return {"type": "http.disconnect"}

    async def send(message):
        sends.append(message)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        for chunk in (b"a", b"b", b"c"):
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
            assert sends[-1]["body"] == chunk  # Forwarded immediately, not at the end.
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def unexpected_handler(request, error):
        pytest.fail("Successful response must not reach error handler")

    boundary = HttpFailureBoundary(app, unexpected_handler, lambda *_: pytest.fail("No failure"))
    await boundary({"type": "http"}, receive, send)
    assert receives == 0
    assert len(sends) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_type", ["websocket", "lifespan"])
async def test_non_http_scopes_remain_untouched(scope_type):
    async def app(scope, receive, send):
        assert scope["type"] == scope_type
        raise ValueError(MARKER)

    async def unused(*_):
        pytest.fail("Non-HTTP scope must not use HTTP handler")

    boundary = HttpFailureBoundary(app, unused, lambda *_: pytest.fail("No HTTP log"))
    with pytest.raises(ValueError, match=MARKER):
        await boundary({"type": scope_type}, unused, unused)


@pytest.mark.asyncio
async def test_malformed_domain_error_projection_still_produces_safe_500():
    async def app(scope, receive, send):
        raise ValueError(MARKER)

    async def malformed_handler(request, error):
        raise TypeError(MARKER)

    async def receive():
        return {"type": "http.request", "body": b""}

    messages = []

    async def send(message):
        messages.append(message)

    boundary = HttpFailureBoundary(app, malformed_handler, lambda *_: None)
    await boundary({"type": "http", "headers": []}, receive, send)
    assert messages[0]["status"] == 500
    assert MARKER.encode() not in messages[1]["body"]


@pytest.mark.asyncio
async def test_failure_while_sending_error_response_does_not_export_transport_body():
    async def app(scope, receive, send):
        raise ValueError(MARKER)

    async def handler(request, error):
        from starlette.responses import JSONResponse

        return JSONResponse({"error": "safe"}, status_code=500)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def broken_send(message):
        raise OSError(MARKER)

    boundary = HttpFailureBoundary(app, handler, lambda *_: None)
    with pytest.raises(HttpResponseAborted) as caught:
        await boundary({"type": "http", "headers": []}, receive, broken_send)
    assert MARKER not in "".join(traceback.format_exception(caught.value))
