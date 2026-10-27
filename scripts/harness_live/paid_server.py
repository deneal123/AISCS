"""Real GigaChat acceptance; deny other providers, never fabricate a response."""

import asyncio
import json
import logging
import os
import sys
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import Header


class PaidGigaGuard:
    def __init__(self, settings, *, model="GigaChat-3-Lightning"):
        assert model in {"GigaChat-3-Lightning", "GigaChat-2-Max"}
        self.model = model
        self.hosts = {
            urlsplit(value).hostname
            for value in (settings.gigachat_base_url, settings.gigachat_oauth_url)
            if value
        }
        self.completions = self.blocked = self.blocked_mutations = 0

    def allows(self, request):
        if request.url.host in {"backend", "workspace"} and request.url.port in {8002, 8082}:
            return True
        if request.url.host not in self.hosts:
            return False
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            if json.loads(request.content).get("model") != self.model:
                return False
            self.completions += 1
            return True
        return request.url.path.endswith("/oauth") or (
            request.method == "GET" and request.url.path.endswith("/models")
        )

    def install(self):
        original = httpx.AsyncHTTPTransport.handle_async_request

        async def guarded(transport, request):
            if not self.allows(request):
                self.blocked += 1
                if request.method != "GET":
                    self.blocked_mutations += 1
                raise httpx.ConnectError("paid_acceptance_transport_denied", request=request)
            return await original(transport, request)

        httpx.AsyncHTTPTransport.handle_async_request = guarded


async def main():
    logging.disable(logging.CRITICAL)
    from service.settings import config

    guard = PaidGigaGuard(
        config.agents, model=os.environ.get("HARNESS_ACCEPTANCE_PAID_MODEL", "GigaChat-3-Lightning")
    )
    guard.install()
    from service.main import app
    from service.presentation.deps import internal_auth

    @app.get("/__harness_acceptance__/transport", include_in_schema=False)
    async def metrics(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        return {
            "paid_completions": guard.completions,
            "blocked_requests": guard.blocked,
            "blocked_mutations": guard.blocked_mutations,
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
