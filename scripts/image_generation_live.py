"""Изолированная проверка FLUX: максимум один реальный запрос, без смены dev-настроек."""

import asyncio
import base64
import hashlib
import json
import logging
import sys
from io import BytesIO
from urllib.parse import urlsplit

import httpx
import uvicorn
from fastapi import Header
from PIL import Image

MODEL = "black-forest-labs/flux-3-image"


class ImageCallGuard:
    def __init__(self, settings):
        self.image_host = urlsplit(settings.routerai_base_url).hostname
        self.text_hosts = {
            urlsplit(url).hostname
            for url in (settings.gigachat_base_url, settings.gigachat_oauth_url)
            if url
        }
        self.read_hosts = self.text_hosts | {
            self.image_host,
            "backend",
            "workspace",
            "openrouter.ai",
        }
        self.image_calls = self.text_calls = self.denied = 0
        self.dimensions = self.image_sha256 = None

    def observe_image(self, payload):
        try:
            content = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
            with Image.open(BytesIO(content)) as image:
                image.verify()
            with Image.open(BytesIO(content)) as image:
                self.dimensions = list(image.size)
            self.image_sha256 = hashlib.sha256(content).hexdigest()
        except (ValueError, KeyError, IndexError, TypeError, OSError):
            self.dimensions = self.image_sha256 = None

    def allows(self, request):
        if request.method == "GET":
            return request.url.host in self.read_hosts
        if request.url.host == self.image_host and request.url.path.endswith("/images"):
            body = json.loads(request.content)
            if body.get("model") != MODEL or body.get("n") != 1 or self.image_calls:
                return False
            self.image_calls += 1
            return True
        if request.url.host in self.text_hosts:
            if request.url.path.endswith("/oauth"):
                return True
            if request.url.path.endswith("/chat/completions"):
                if json.loads(request.content).get("model") != "GigaChat-3-Lightning":
                    return False
                self.text_calls += 1
                return self.text_calls <= 4
        return request.url.host in {"backend", "workspace"}

    def install(self):
        original = httpx.AsyncHTTPTransport.handle_async_request

        async def guarded(transport, request):
            if not self.allows(request):
                self.denied += 1
                raise httpx.ConnectError("image_acceptance_transport_denied", request=request)
            response = await original(transport, request)
            if request.url.host == self.image_host and request.url.path.endswith("/images"):
                if response.status_code == 200:
                    self.observe_image(json.loads(await response.aread()))
            return response

        httpx.AsyncHTTPTransport.handle_async_request = guarded


async def main():
    logging.disable(logging.CRITICAL)
    from service.settings import config

    # Только изолированная приёмка: основной dev-процесс остаётся выключенным.
    # Backend до доставки задания проверяет цену и предел оператора.
    config.agents.image_only_api_enabled = True
    guard = ImageCallGuard(config.agents)
    guard.install()
    # Выбор конкретного генератора относится только к этому проверочному процессу.
    # Admission, метаданные и реальные transport/billing не заменяются.
    from service.domain.subagents import utils

    utils._PREFERRED_IMAGE_MODELS = (MODEL,)
    from service.main import app
    from service.presentation.deps import internal_auth

    @app.get("/__image_acceptance__/metrics", include_in_schema=False)
    async def metrics(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        from service.domain.client.providers.management.snapshot import build_run_provider_admission

        admission = await build_run_provider_admission()
        try:
            record = next(
                (
                    item
                    for item in admission.snapshot.records.get("routerai", ())
                    if item.model_id == MODEL
                ),
                None,
            )
            return {
                "image_calls": guard.image_calls,
                "text_calls": guard.text_calls,
                "flux_admitted": bool(record and record.supports("image_output")),
                "flux_chat": bool(record and record.supports("chat")),
                "dimensions": guard.dimensions,
                "image_sha256": guard.image_sha256,
            }
        finally:
            admission.snapshot.release()

    server = uvicorn.Server(
        uvicorn.Config(app, host="0.0.0.0", port=8091, access_log=False, log_level="critical")
    )
    task = asyncio.create_task(server.serve())
    await asyncio.to_thread(sys.stdin.buffer.read, 1)
    server.should_exit = True
    await task


if __name__ == "__main__":
    asyncio.run(main())
