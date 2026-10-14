"""Transport errors must not reflect request values or exception bodies."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from domain.policy import WorkspacePolicy
from fastapi import FastAPI
from presentation import workspace_routes
from presentation.http import app, http_error
from starlette.exceptions import HTTPException

from drivers.base import DriverError

MARKER = "private-input-sentinel https://private.example/capability"


async def test_validation_error_never_reflects_input():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workspaces",
            json={
                "user_id": {"private": MARKER},
                "ttl_sec": MARKER,
            },
        )
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert MARKER not in response.text
    assert "private.example" not in response.text


@pytest.mark.parametrize("status", [401, 403, 404, 413, 500])
async def test_http_exception_detail_is_not_a_wire_message(status):
    fixture = FastAPI()
    fixture.add_exception_handler(HTTPException, http_error)

    @fixture.get("/failure")
    async def failure():
        raise HTTPException(status_code=status, detail={"private": MARKER})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture), base_url="http://test"
    ) as client:
        response = await client.get("/failure")
    assert response.status_code == status
    assert MARKER not in response.text
    assert "private.example" not in response.text


async def test_exception_detail_is_never_stringified():
    class PrivateDetail:
        def __str__(self):
            raise AssertionError("private detail must not be evaluated")

    response = await http_error(None, HTTPException(500, detail=PrivateDetail()))
    assert response.status_code == 500
    assert response.body == b'{"error":"internal","detail":"workspace request failed"}'


async def test_uncaught_driver_failure_uses_safe_typed_http_outcome():
    fixture = FastAPI()
    fixture.exception_handlers.update(app.exception_handlers)

    @fixture.get("/driver-failure")
    async def driver_failure():
        raise DriverError(MARKER)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture), base_url="http://test"
    ) as client:
        response = await client.get("/driver-failure")
    assert response.status_code == 502
    assert response.json() == {"error": "driver_failed", "detail": "workspace driver failed"}
    assert MARKER not in response.text


async def test_file_read_driver_failure_is_bounded_and_not_retried(monkeypatch, caplog):
    monkeypatch.setattr(workspace_routes, "SERVICE_KEY", "fixture-service-key")
    monkeypatch.setattr(workspace_routes, "registry", None)
    monkeypatch.setattr(
        workspace_routes, "_resolve", lambda *_: SimpleNamespace(policy=WorkspacePolicy())
    )
    operation = AsyncMock(side_effect=DriverError(MARKER))
    monkeypatch.setattr(workspace_routes, "_run_file_op", operation)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/workspaces/owned-fixture/files/read",
            headers={"Authorization": "Bearer fixture-service-key"},
            json={"user_id": "owner", "token": "fixture-token", "path": "test.txt"},
        )
    assert response.status_code == 502
    assert response.json() == {"error": "driver_failed", "detail": "workspace driver failed"}
    operation.assert_awaited_once()
    assert MARKER not in response.text
    assert MARKER not in caplog.text
    records = [r for r in caplog.records if getattr(r, "failure_code", "") == "driver_failed"]
    assert len(records) == 1
    assert records[0].component == "workspace_driver"
    assert records[0].exc_info is None


async def test_transport_driver_handler_does_not_convert_cancellation(caplog):
    fixture = FastAPI()
    fixture.exception_handlers.update(app.exception_handlers)

    @fixture.get("/cancel")
    async def cancelled():
        raise asyncio.CancelledError

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fixture), base_url="http://test"
    ) as client:
        with pytest.raises(asyncio.CancelledError):
            await client.get("/cancel")
    assert not [r for r in caplog.records if getattr(r, "failure_code", "") == "driver_failed"]
