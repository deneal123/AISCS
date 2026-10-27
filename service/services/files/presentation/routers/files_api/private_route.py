"""Cache policy for authenticated file metadata and short-lived capabilities."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.routing import APIRoute
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response


def _private_headers(headers: MutableHeaders) -> None:
    headers["Cache-Control"] = "private, no-store"
    headers["Pragma"] = "no-cache"
    existing = [value.strip() for value in headers.get("Vary", "").split(",") if value.strip()]
    seen = {value.lower() for value in existing}
    if "*" not in seen:
        existing.extend(value for value in ("Cookie", "Authorization") if value.lower() not in seen)
    headers["Vary"] = ", ".join(existing)


class PrivateFileRoute(APIRoute):
    """Keep success and bounded HTTP errors out of browser/shared caches."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except HTTPException as exc:
                headers = MutableHeaders(headers=exc.headers or {})
                _private_headers(headers)
                exc.headers = dict(headers)
                raise
            _private_headers(response.headers)
            return response

        return handler
