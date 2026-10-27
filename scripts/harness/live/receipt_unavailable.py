"""Только fixture: первый точный usage RPC не доходит до backend handler."""

import json


class ReceiptUnavailableMiddleware:
    def __init__(self, app, fault):
        self.app, self.fault = app, fault

    async def __call__(self, scope, receive, send):
        if scope.get("path") != "/internal/harness/v1/exchange" or self.fault.count:
            return await self.app(scope, receive, send)
        messages, body = [], bytearray()
        while True:
            message = await receive()
            messages.append(message)
            body.extend(message.get("body", b""))
            if not message.get("more_body"):
                break
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {}
        if self.fault.matches(payload):
            self.fault.count += 1
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"private, no-store"),
                    ],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"detail":{"code":"checkpoint_unavailable"}}',
                }
            )
            return

        async def replay():
            return messages.pop(0) if messages else await receive()

        await self.app(scope, replay, send)
