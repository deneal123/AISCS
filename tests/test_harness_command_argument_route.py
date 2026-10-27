"""Private validation rejection is acknowledged before any executor construction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from service.services.chat.presentation.routers import harness_commands


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_invalid_recipe_reconciles_safely_even_when_new_commands_are_disabled(
    monkeypatch, enabled
):
    app = FastAPI()
    app.include_router(harness_commands.router)
    app.state.container = SimpleNamespace(infra=SimpleNamespace(pg_connector=None))
    owner, operation = object(), uuid4()
    monkeypatch.setattr(harness_commands, "authorize", lambda _: owner)
    monkeypatch.setattr(
        harness_commands, "settings", lambda: SimpleNamespace(ide_commands_enabled=enabled)
    )
    saved = AsyncMock()
    monkeypatch.setattr(harness_commands.IdeCommandRepository, "reject_invalid_command", saved)
    executor = Mock(side_effect=AssertionError("executor must not be built"))
    monkeypatch.setattr(harness_commands, "build_agent_console", executor)
    arguments = {"profile": "python_script", "target": "a.py", "command": "PRIVATE_VALUE"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/commands",
            json={"action": "run", "operation_id": str(operation), "spec": arguments},
            headers={"Authorization": "Bearer fixture"},
        )
    assert response.status_code == 409 and "PRIVATE_VALUE" not in response.text
    assert response.json() == {"detail": {"code": "harness_request_invalid"}}
    assert response.headers["cache-control"] == "private, no-store"
    saved.assert_awaited_once_with(owner, operation, arguments)
    executor.assert_not_called()
