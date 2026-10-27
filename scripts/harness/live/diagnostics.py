"""Observational ASGI tee: no body substitution, executor or policy overrides."""

import json
import logging
import re


class CommandFailures(logging.Handler):
    def emit(self, record):
        print(
            json.dumps(
                {"stage": "console_failure", "phase": record.phase, "code": record.failure_code}
            ),
            flush=True,
        )


def observe_command_failures():
    logging.disable(logging.NOTSET)
    logging.getLogger().setLevel(logging.CRITICAL)
    for value in logging.Logger.manager.loggerDict.values():
        if isinstance(value, logging.Logger):
            value.setLevel(logging.CRITICAL)
    target = logging.getLogger("gpthub.ide.command")
    target.setLevel(logging.WARNING)
    target.addHandler(CommandFailures())
    target.propagate = False


class PermitDiagnostics:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        status = 200

        async def observed(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            if (
                message["type"] == "http.response.body"
                and scope.get("path") == "/internal/workspace-coordination/ide/command"
                and status >= 400
            ):
                try:
                    payload = json.loads(message.get("body", b""))
                    code = payload.get("detail", payload.get("error", {})).get("code", "")
                    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                        print(
                            json.dumps({"stage": "command_permit", "code": code, "status": status}),
                            flush=True,
                        )
                except (ValueError, AttributeError):
                    pass
            await send(message)

        await self.app(scope, receive, observed)
