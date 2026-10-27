"""Перезапуск только собственного agents-процесса с журналом транспортного double."""

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import Header

_STATE = "HARNESS_ACCEPTANCE_TRANSPORT_STATE"
_FIELDS = {"completions", "tool_names", "blocked_requests", "oauth", "tool_states"}


class RefuseRecoveredRuns:
    """Сетевой отказ только в изолированной приёмке исчерпания retry."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        mode = os.environ.get("HARNESS_ACCEPTANCE_RESTART_EXHAUSTED")
        refused = scope.get("path") == "/run" and (
            mode == "before_dispatch"
            or (
                mode == "after_write"
                and os.environ.get("HARNESS_ACCEPTANCE_AGENTS_RESTARTED") == "1"
            )
        )
        if not refused:
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 503, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})


def restore_transport(provider):
    raw = os.environ.pop(_STATE, None)
    if raw is None:
        return
    assert len(raw.encode()) <= 16384
    saved = json.loads(raw)
    assert set(saved) == _FIELDS
    assert all(
        type(saved[key]) is int and 0 <= saved[key] <= 100
        for key in (
            "completions",
            "blocked_requests",
            "oauth",
        )
    )
    assert isinstance(saved["tool_names"], list) and len(saved["tool_names"]) <= 100
    assert isinstance(saved["tool_states"], dict) and len(saved["tool_states"]) <= 100
    for key, value in saved.items():
        setattr(provider, key, value)


def install_restart(app, provider):
    from service.presentation.deps import internal_auth

    identity = uuid4().hex
    app.add_middleware(RefuseRecoveredRuns)

    @app.get("/__harness_acceptance__/instance", include_in_schema=False)
    async def instance(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        return {"instance": identity}

    @app.post("/__harness_acceptance__/restart", include_in_schema=False)
    async def restart(authorization: str | None = Header(default=None)):
        internal_auth(authorization)
        assert os.environ.get("HARNESS_ACCEPTANCE_AGENTS_RESTARTED") != "1"
        saved = json.dumps({key: getattr(provider, key) for key in _FIELDS})
        assert len(saved.encode()) <= 16384
        os.environ[_STATE] = saved
        os.environ["HARNESS_ACCEPTANCE_AGENTS_RESTARTED"] = "1"
        root = str(Path(__file__).resolve().parents[2])
        bootstrap = (
            "import runpy,sys;sys.path.insert(0,sys.argv[1]);"
            "runpy.run_module('scripts.harness_live.server',run_name='__main__')"
        )
        asyncio.get_running_loop().call_later(
            0.2, os.execv, sys.executable, [sys.executable, "-c", bootstrap, root]
        )
        return {"restarting": identity}
