"""Opt-in isolated real Uvicorn probes; never inject faults into the dev stack."""

import logging
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse

from service.shared.presentation.handlers import exceptions_handlers as handlers

MARKER = "PRIVATE_REAL_SERVER_EXCEPTION_MARKER"
pytestmark = pytest.mark.skipif(
    os.environ.get("S37_LIVE_HTTP_PRIVACY") != "1", reason="opt-in isolated server probe"
)


@pytest.mark.parametrize("path", ["/fail", "/stream"])
def test_real_server_error_log_has_no_private_exception(path, monkeypatch, caplog):
    for name in (handlers.logger.name, "uvicorn.error"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", [caplog.handler])
        monkeypatch.setattr(logger, "propagate", False)
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.INFO)
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.WARNING)
    app = FastAPI()
    handlers.setup_exception_handlers(app)

    @app.get("/fail")
    async def fail(request: Request):
        raise RuntimeError(request.query_params["private"])

    @app.get("/stream")
    async def stream(request: Request):
        async def chunks():
            yield b"first"
            raise RuntimeError(request.query_params["private"])

        return StreamingResponse(chunks())

    # Access logging is deliberately excluded: this proves exception-body
    # redaction, not generic query-string privacy of server/proxy access logs.
    config = uvicorn.Config(app, log_config=None, access_log=False, lifespan="off", loop="asyncio")
    server = uvicorn.Server(config)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started, "isolated_server_start_failed"
            port = listener.getsockname()[1]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
                if path == "/fail":
                    response = client.get(path, params={"private": MARKER})
                    assert response.status_code == 500
                    assert response.json()["error"]["code"] == "internal_error"
                    assert MARKER not in response.text
                else:
                    with client.stream("GET", path, params={"private": MARKER}) as response:
                        assert response.status_code == 200
                        chunks = []
                        with pytest.raises(httpx.RemoteProtocolError):
                            for chunk in response.iter_bytes():
                                chunks.append(chunk)
                        assert b"".join(chunks) == b"first"
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if thread.is_alive():
                server.force_exit = True
                thread.join(timeout=2)
            assert not thread.is_alive(), "isolated_server_cleanup_failed"
    records = [record for record in caplog.records if record.name == handlers.logger.name]
    assert len(records) == 1
    assert records[0].failure_code == "internal"
    assert records[0].status_code == 500
    assert records[0].exc_info is None
    assert MARKER not in caplog.text
    server_errors = [
        record for record in caplog.records if record.name == "uvicorn.error" and record.exc_info
    ]
    assert len(server_errors) == (1 if path == "/stream" else 0)
