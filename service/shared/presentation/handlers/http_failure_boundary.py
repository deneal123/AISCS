"""Prevent unhandled HTTP bodies from reaching the ASGI server's traceback log."""

from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from service.shared.error_handling.error_mapper import map_exception_to_error_response


class HttpResponseAborted(RuntimeError):
    """A response cannot be replaced after its headers have been sent."""

    def __init__(self) -> None:
        super().__init__("HTTP response interrupted")


class HttpFailureBoundary:
    """Pure ASGI middleware: do not read, buffer or complete a failed stream.

    Known errors remain handled by the inner ExceptionMiddleware. Unknown
    pre-response errors produce the existing safe response without Starlette's
    raw re-raise. Once headers have been sent, the server must still observe a
    failure and close the connection, but it receives only a bounded exception.
    BaseException (notably cancellation) and non-HTTP scopes pass unchanged.
    """

    def __init__(
        self,
        app: ASGIApp,
        error_handler: Callable[[Request, Exception], Awaitable[Response]],
        failure_reporter: Callable[[str, int], None],
    ) -> None:
        self.app = app
        self.error_handler = error_handler
        self.failure_reporter = failure_reporter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, guarded_send)
        except Exception as exc:
            if started:
                self.failure_reporter("internal", 500)
                # Suppress both raw causes and nested ExceptionGroup formatting.
                raise HttpResponseAborted() from None
            try:
                response = await self.error_handler(Request(scope), exc)
            except Exception:
                # A malformed domain error must not bypass the boundary when
                # response projection itself fails. Do not stringify it.
                payload = map_exception_to_error_response(RuntimeError())
                response = JSONResponse(status_code=500, content=payload.model_dump())
            try:
                await response(scope, receive, guarded_send)
            except Exception:
                # Includes failures in the transport while sending the fallback.
                raise HttpResponseAborted() from None
