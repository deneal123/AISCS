import asyncio
import hashlib
import time
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from application.ide_bundles import BundleTransferFailure, IdeBundleService
from domain.contracts import ERROR_CODES
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from infrastructure.ide_bundle_format import BundleFailure
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_capture import _OwnedResponse, create_ide_capture_router
from test_ide_bundles import LIMITS, capture_driver


def fixture():
    state = SimpleNamespace(
        locked=False,
        captures=0,
        guards=0,
        reads=0,
        changed=False,
        capture_error=None,
        deny=0,
        closed=False,
        source=None,
    )
    item = SimpleNamespace(
        ref="private",
        expires_at=int(time.time()) + 300,
        policy=SimpleNamespace(root="/workspace", exec_timeout_sec=10, quota_bytes=65536),
    )
    item.expired = lambda: item.expires_at <= time.time()
    driver = capture_driver()

    @asynccontextmanager
    async def operation(value):
        assert value is item and not state.locked
        state.locked = True
        try:
            yield
        finally:
            state.locked = False

    @asynccontextmanager
    async def capture(value, limits):
        assert state.locked and value is item and limits == LIMITS
        state.captures += 1
        if state.capture_error:
            raise state.capture_error
        async with IdeBundleService(driver, source="trusted").capture_verified(
            item, limits
        ) as result:
            state.source = result.source
            if state.changed:
                item.expires_at = 1
            yield result
        state.closed = True

    async def guard(*args, **kwargs):
        assert state.locked and args[1] == "capture"
        assert kwargs == {"workspace_id": "owned"}
        state.guards += 1
        return (
            JSONResponse({}, status_code=403)
            if state.guards == state.deny
            else SimpleNamespace(allowed=True)
        )

    def auth(value):
        if value != "Bearer service":
            raise HTTPException(401)

    def owned(workspace_id, payload):
        state.reads += 1
        if workspace_id != "owned" or payload.user_id != "owner" or payload.token != "private":
            return None, JSONResponse({"error": "forbidden"}, status_code=403)
        return item, None

    def error(code, detail, status):
        assert code in ERROR_CODES
        return JSONResponse({"error": code, "detail": detail}, status_code=status)

    registry = SimpleNamespace(operation=operation, capture_ide=capture)
    deps = WorkspaceRouteDependencies(
        auth,
        error,
        lambda: registry,
        owned,
        guard,
        lambda value: isinstance(value, JSONResponse),
        None,
        None,
        None,
        None,
    )
    app = FastAPI()
    app.include_router(create_ide_capture_router(deps))
    return TestClient(app), state, driver, item


def body(item):
    return dict(
        user_id="owner",
        token="private",
        expected_expires_at=item.expires_at,
        coordination_capability="capability",
        limits=asdict(LIMITS),
    )


def test_capture_exposes_only_verified_binary_after_two_owned_guards_and_closes_spool():
    client, state, driver, item = fixture()
    response = client.post(
        "/workspaces/owned/ide/capture",
        json=body(item),
        headers={"Authorization": "Bearer service"},
    )
    assert response.status_code == 200 and response.content == driver.body
    assert response.headers["x-ide-capsule-sha256"] == hashlib.sha256(response.content).hexdigest()
    assert response.headers["content-length"] == str(len(response.content))
    assert response.headers["cache-control"] == "no-store"
    assert state.captures == 1 and state.guards == 2 and state.reads == 3
    assert not state.locked and state.closed and state.source.closed


@pytest.mark.parametrize(
    "change,status",
    [
        ({"user_id": "other"}, 403),
        ({"token": "wrong"}, 403),
        ({"expected_expires_at": 1}, 409),
        ({"path": "/etc"}, 422),
        ({"command": "sh"}, 422),
        ({"expected_expires_at": True}, 422),
    ],
)
def test_capture_denies_ownership_generation_and_unknown_fields_before_dispatch(change, status):
    client, state, _, item = fixture()
    response = client.post(
        "/workspaces/owned/ide/capture",
        json={**body(item), **change},
        headers={"Authorization": "Bearer service"},
    )
    assert response.status_code == status and state.captures == 0


def test_capture_does_not_run_without_service_authorization():
    client, state, _, item = fixture()
    assert client.post("/workspaces/owned/ide/capture", json=body(item)).status_code == 401
    assert state.captures == state.reads == 0


@pytest.mark.parametrize(
    "denial", ["initial", "after_capture", "expired", "quota", "busy", "unknown"]
)
def test_capture_denial_never_sends_capsule_bytes_or_retires_the_user_runtime(denial):
    client, state, driver, item = fixture()
    request = body(item)
    expected = 503
    if denial == "initial":
        state.deny, expected = 1, 403
    if denial == "after_capture":
        state.deny, expected = 2, 403
    if denial == "expired":
        state.changed, expected = True, 409
    if denial == "quota":
        request["limits"]["archive_bytes"], expected = 100000, 413
    if denial == "busy":
        state.capture_error, expected = BundleFailure("ide_bundle_busy"), 409
    if denial == "unknown":
        state.capture_error = BundleTransferFailure(False)
    response = client.post(
        "/workspaces/owned/ide/capture", json=request, headers={"Authorization": "Bearer service"}
    )
    assert response.status_code == expected
    assert "x-ide-capsule-sha256" not in response.headers
    assert driver.body not in response.content and b"private code" not in response.content
    assert not state.locked
    if state.source is not None:
        assert state.source.closed


@pytest.mark.asyncio
async def test_send_failure_releases_owned_response_resources_without_a_background_task():
    closed = []
    resources = AsyncExitStack()

    @asynccontextmanager
    async def owner():
        try:
            yield
        finally:
            closed.append(True)

    await resources.enter_async_context(owner())

    async def chunks():
        yield b"verified"

    async def send(event):
        if event["type"] == "http.response.body":
            raise OSError("disconnected")

    async def receive():
        await asyncio.Event().wait()

    response = _OwnedResponse(chunks(), resources)
    with pytest.raises(ExceptionGroup) as caught:
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    assert len(caught.value.exceptions) == 1
    assert isinstance(caught.value.exceptions[0], OSError)
    assert closed == [True]
