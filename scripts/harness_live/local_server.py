"""Настоящий локальный transport; любые внешние model endpoints запрещены."""

import asyncio
import json
import logging
import os
import sys

import httpx
import uvicorn
from fastapi import Header


class LocalGuard:
    def __init__(self):
        self.completions = self.blocked = 0
        self.responses = []

    def install(self):
        original = httpx.AsyncHTTPTransport.handle_async_request

        async def guarded(transport, request):
            allowed = request.url.host in {"backend", "workspace"} and request.url.port in {
                8002,
                8082,
            }
            local = request.url.host == "local-llm" and request.url.port == 8080
            if local and request.url.path == "/v1/chat/completions" and request.method == "POST":
                if json.loads(request.content).get("model") == "qwen2.5-1.5b-instruct":
                    self.completions += 1
                    allowed = True
            if local and request.url.path == "/v1/models" and request.method == "GET":
                allowed = True
            if not allowed:
                self.blocked += 1
                raise httpx.ConnectError("local_acceptance_transport_denied", request=request)
            try:
                response = await original(transport, request)
            except httpx.TransportError as error:
                if local and request.method == "POST":
                    self.responses.append({"error": type(error).__name__})
                raise
            if local and request.method == "POST":
                self.responses.append({"status": response.status_code})
            return response

        httpx.AsyncHTTPTransport.handle_async_request = guarded


async def main():
    logging.disable(logging.CRITICAL)
    payload = json.loads(sys.stdin.buffer.readline())
    key = payload.pop("key")
    assert len(key) >= 32 and not payload
    os.environ.update(
        AGENTS__LOCAL_API_KEY=key,
        AGENTS__LOCAL_BASE_URL="http://local-llm:8080/v1",
        AGENTS__HARNESS_REFINEMENT_ENABLED="true",
        AGENTS__CHAT_MAX_TOKENS="1024",
    )
    guard = LocalGuard()
    guard.install()
    from service.main import app
    from service.presentation.deps import internal_auth

    @app.get("/__harness_acceptance__/transport", include_in_schema=False)
    async def metrics(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        return {
            "completions": guard.completions,
            "blocked_requests": guard.blocked,
            "responses": guard.responses,
        }

    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8091, access_log=False, log_level="critical")
    )
    task = asyncio.create_task(server.serve())
    await asyncio.to_thread(sys.stdin.buffer.read, 1)
    server.should_exit = True
    await task


if __name__ == "__main__":
    asyncio.run(main())
