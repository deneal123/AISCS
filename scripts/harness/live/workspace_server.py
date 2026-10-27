"""Disposable workspace server; fault injection changes ACKs, never execution."""

import asyncio
import json
import os
import re
import sys
from uuid import uuid4


class DispatchAckBoundary:
    def __init__(self, app, *, enabled=False):
        self.app, self.enabled = app, enabled
        self.lost = 0
        self.attempts = {action: 0 for action in ("create", "handshake", "dispatch")}
        self.operations = set()

    def metrics(self):
        return {"lost": self.lost, "attempts": self.attempts, "operations": len(self.operations)}

    async def __call__(self, scope, receive, send):
        if not re.fullmatch(r"/workspaces/[^/]+/ide/commands", scope.get("path", "")):
            return await self.app(scope, receive, send)
        body, drop = bytearray(), False
        payload = None

        async def observed_receive():
            nonlocal payload
            message = await receive()
            body.extend(message.get("body", b""))
            if message["type"] == "http.request" and not message.get("more_body"):
                payload = json.loads(body)
                action = payload.get("action")
                if action in self.attempts:
                    self.attempts[action] += 1
                    self.operations.add(payload.get("operation_id"))
            return message

        async def observed_send(message):
            nonlocal drop
            if (
                message["type"] == "http.response.start"
                and message["status"] == 200
                and self.enabled
                and self.lost == 0
                and isinstance(payload, dict)
                and payload.get("action") == "dispatch"
            ):
                # The real route already sent GO through its real Engine stream.
                # Lose only its response to backend; status/Stop remain untouched.
                self.lost += 1
                drop = True
                message = {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"private, no-store"),
                    ],
                }
            if drop and message["type"] == "http.response.body":
                if message.get("more_body"):
                    return
                message = {
                    "type": "http.response.body",
                    "body": b'{"error":"workspace_unavailable","detail":"ack unavailable"}',
                }
            await send(message)

        await self.app(scope, observed_receive, observed_send)


class DocumentAckBoundary:
    """Убирает только первый успешный ACK proposals/builds, не вызов исполнителя."""

    def __init__(self, app):
        self.app = app
        self.lost = {"proposals": 0, "builds": 0}
        self.attempts = {"proposals": 0, "builds": 0}
        self.identities = {"proposals": set(), "builds": set()}

    def metrics(self):
        return {
            "lost": self.lost,
            "attempts": self.attempts,
            "identities": {key: len(value) for key, value in self.identities.items()},
        }

    async def __call__(self, scope, receive, send):
        match = re.fullmatch(
            r"/workspaces/[^/]+/documents/(proposals|builds)", scope.get("path", "")
        )
        if not match or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        action = match[1]
        self.attempts[action] += 1
        drop, success, body = False, False, bytearray()

        async def observed_send(message):
            nonlocal drop, success
            if message["type"] == "http.response.start":
                success = message["status"] == 200
                drop = success and self.lost[action] == 0
                if drop:
                    self.lost[action] += 1
                    message = {
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"private, no-store"),
                        ],
                    }
            if message["type"] == "http.response.body" and success:
                body.extend(message.get("body", b""))
                if message.get("more_body"):
                    if drop:
                        return
                else:
                    value = json.loads(body)
                    self.identities[action].add(
                        value["proposal_id" if action == "proposals" else "build_id"]
                    )
                    if drop:
                        message = {
                            "type": "http.response.body",
                            "body": b'{"error":"workspace_unavailable"}',
                        }
            await send(message)

        await self.app(scope, receive, observed_send)


async def serve():
    import uvicorn
    from fastapi import Header
    from presentation.http import app
    from presentation.workspace_routes import _auth

    mode = os.environ.get("HARNESS_ACCEPTANCE_WORKSPACE_FAULT", "")
    assert mode in {"", "dispatch_ack", "restart_complete", "restart_stop", "document_acks"}
    boundary = (
        DocumentAckBoundary(app)
        if mode == "document_acks"
        else DispatchAckBoundary(app, enabled=mode == "dispatch_ack")
    )
    instance = uuid4().hex

    @app.get("/__harness_acceptance__/workspace")
    async def metrics(authorization: str | None = Header(default=None)):
        _auth(authorization)
        return boundary.metrics()

    if mode.startswith("restart_"):

        @app.get("/__harness_acceptance__/instance")
        async def identity(authorization: str | None = Header(default=None)):
            _auth(authorization)
            return {"instance": instance}

        @app.post("/__harness_acceptance__/restart")
        async def restart(authorization: str | None = Header(default=None)):
            _auth(authorization)
            assert os.environ.get("HARNESS_ACCEPTANCE_WORKSPACE_RESTARTED") != "1"
            os.environ["HARNESS_ACCEPTANCE_WORKSPACE_RESTARTED"] = "1"
            bootstrap = (
                "import sys;sys.path.insert(0,sys.argv[1]);"
                "import workspace_server;workspace_server.main()"
            )
            # Replace only this disposable server's process image. Engine,
            # sandbox and journal survive; all observer sessions/streams do not.
            asyncio.get_running_loop().call_later(
                0.2, os.execv, sys.executable, [sys.executable, "-c", bootstrap, sys.argv[1]]
            )
            return {"restarting": instance}

    server = uvicorn.Server(
        uvicorn.Config(boundary, host="0.0.0.0", port=8082, access_log=False, log_level="critical")
    )
    task = asyncio.create_task(server.serve())
    await asyncio.to_thread(sys.stdin.buffer.read, 1)
    server.should_exit = True
    await task


def main():
    asyncio.run(serve())
