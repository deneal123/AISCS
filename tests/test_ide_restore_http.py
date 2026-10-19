import asyncio
import hashlib
import io
import json
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from application.allocations import AllocationConflict, AllocationExpired, AllocationPending
from application.lifecycle import TooManyWorkspaces, WorkspaceRegistry
from application.recovery import RestoreSnapshot
from domain.contracts import ERROR_CODES
from domain.policy import WorkspacePolicy
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from infrastructure.ide_bundle_format import BundleFailure, BundleLimits
from presentation.routes.dependencies import WorkspaceRouteDependencies
from presentation.routes.ide_restore import create_ide_restore_router
from test_ide_bundles import capsule
from test_ide_restore_lifecycle import driver as lifecycle_driver

from drivers import DriverError, IsolationUnverified
from drivers.binary_exec import BinaryExecReply

BODY = b"owned capsule fixture"
LIMITS = BundleLimits(16, 1024, 4096, 16384, 8192, 8)


@pytest.fixture
def setup(monkeypatch):
    payload = {
        "user_id": "owner",
        "allocation": {"allocation_id": str(uuid4()), "expires_at": int(time.time()) + 300},
        "snapshot": {"size": len(BODY), "sha256": hashlib.sha256(BODY).hexdigest()},
        "limits": asdict(LIMITS),
    }
    state = SimpleNamespace(files=[], received=None, failure=None)

    def spool(**kwargs):
        result = SpooledTemporaryFile(**kwargs)
        state.files.append(result)
        return result

    monkeypatch.setattr("presentation.routes.ide_restore.SpooledTemporaryFile", spool)

    async def restore(user, policy, **kwargs):
        assert user == "owner" and policy == WorkspacePolicy()
        assert kwargs["allocation"].allocation_id == UUID(payload["allocation"]["allocation_id"])
        assert kwargs["allocation"].expires_at == payload["allocation"]["expires_at"]
        assert kwargs["limits"] == LIMITS
        assert kwargs["expected_size"] == len(BODY)
        assert kwargs["expected_sha256"] == payload["snapshot"]["sha256"]
        state.received = kwargs["source"].read()
        if state.failure:
            raise state.failure
        return SimpleNamespace(
            workspace_id="new-owned-runtime",
            policy=policy,
            expires_at=payload["allocation"]["expires_at"],
            restore_snapshot=RestoreSnapshot(payload["snapshot"]["sha256"], len(BODY)),
        ), "private-token"

    registry = SimpleNamespace(create_restored=AsyncMock(side_effect=restore))

    def auth(value):
        if value != "Bearer service":
            raise HTTPException(401)

    def error(code, detail, status):
        assert code in ERROR_CODES
        return JSONResponse({"error": code, "detail": detail}, status_code=status)

    deps = WorkspaceRouteDependencies(
        auth,
        error,
        lambda: registry,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    app = FastAPI()
    app.include_router(create_ide_restore_router(deps))
    return TestClient(app), payload, state, registry


def headers(payload, **changes):
    return {
        "Authorization": "Bearer service",
        "Content-Type": "application/octet-stream",
        "X-IDE-Restore-Request": json.dumps(payload),
        **changes,
    }


def test_verified_bytes_reach_only_fresh_restore_with_exact_allocation_and_closed_spool(setup):
    client, payload, state, registry = setup
    response = client.post(
        "/workspaces/allocations/restore", content=BODY, headers=headers(payload)
    )
    assert response.status_code == 200
    assert response.json()["workspace_id"] == "new-owned-runtime"
    assert response.json()["expires_at"] == payload["allocation"]["expires_at"]
    assert response.json()["restore_snapshot"] == payload["snapshot"]
    assert response.headers["cache-control"] == "no-store"
    assert state.received == BODY and registry.create_restored.await_count == 1
    assert len(state.files) == 1 and state.files[0].closed


def test_authentication_precedes_parsing_or_body_spooling(setup):
    client, _, state, registry = setup
    response = client.post(
        "/workspaces/allocations/restore",
        content=BODY,
        headers={"X-IDE-Restore-Request": "not-json"},
    )
    assert response.status_code == 401
    assert not state.files and registry.create_restored.await_count == 0


@pytest.mark.parametrize(
    "case,status",
    [
        ("ready", 200),
        ("missing", 404),
        ("pending", 409),
        ("conflict", 409),
        ("different", 409),
        ("plain", 409),
        ("expired", 410),
        ("extra", 422),
        ("unauthorized", 401),
    ],
)
def test_restore_lookup_is_exact_passive_and_never_rearms_a_missing_result(setup, case, status):
    client, payload, state, registry = setup
    metadata = {key: value for key, value in payload.items() if key != "limits"}
    item = SimpleNamespace(
        workspace_id="new-owned-runtime",
        policy=WorkspacePolicy(),
        expires_at=payload["allocation"]["expires_at"],
        restore_snapshot=RestoreSnapshot(payload["snapshot"]["sha256"], len(BODY)),
    )
    registry.lookup_allocation = Mock(return_value=None if case == "missing" else item)
    registry.allocation_token = Mock(return_value="private-token")
    if case == "pending":
        registry.lookup_allocation.side_effect = AllocationPending
    if case == "conflict":
        registry.lookup_allocation.side_effect = AllocationConflict
    if case == "different":
        item.restore_snapshot = RestoreSnapshot("a" * 64, len(BODY))
    if case == "plain":
        item.restore_snapshot = None
    if case == "expired":
        metadata["allocation"]["expires_at"] = 1
    if case == "extra":
        metadata["path"] = "/existing-repository"
    request_headers = headers(metadata)
    if case == "unauthorized":
        del request_headers["Authorization"]
    response = client.post("/workspaces/allocations/restore/lookup", headers=request_headers)
    assert response.status_code == status
    if status == 200:
        assert response.json()["restore_snapshot"] == payload["snapshot"]
        assert response.headers["cache-control"] == "no-store"
    else:
        assert "private-token" not in response.text
    if case in {"expired", "extra", "unauthorized"}:
        registry.lookup_allocation.assert_not_called()
    assert not state.files and registry.create_restored.await_count == 0


@pytest.mark.parametrize(
    "case",
    ["missing", "malformed", "large", "extra", "boolean", "digest", "limits", "expired", "quota"],
)
def test_invalid_metadata_never_reads_capsule_or_allocates(setup, case):
    client, payload, state, registry = setup
    expected = 422
    if case == "extra":
        payload["path"] = "/existing-repository"
    if case == "boolean":
        payload["snapshot"]["size"] = True
    if case == "digest":
        payload["snapshot"]["sha256"] = "PRIVATE RAW BODY"
    if case == "limits":
        payload["limits"]["depth"] = True
    if case == "expired":
        payload["allocation"]["expires_at"], expected = 1, 410
    if case == "quota":
        payload["limits"]["archive_bytes"], expected = 1024 * 1024 * 1024, 413
    request_headers = headers(payload)
    if case == "missing":
        del request_headers["X-IDE-Restore-Request"]
    if case == "malformed":
        request_headers["X-IDE-Restore-Request"] = "PRIVATE RAW BODY"
    if case == "large":
        request_headers["X-IDE-Restore-Request"] = "x" * 4097
    response = client.post("/workspaces/allocations/restore", content=BODY, headers=request_headers)
    assert response.status_code == expected
    assert "PRIVATE RAW BODY" not in response.text
    assert not state.files and registry.create_restored.await_count == 0


@pytest.mark.parametrize(
    "case",
    ["duplicate_metadata", "type", "length", "encoding", "transfer", "short", "long", "digest"],
)
def test_body_framing_and_integrity_fail_closed_before_runtime_dispatch(setup, case):
    client, payload, state, registry = setup
    request_headers, body = headers(payload), BODY
    if case == "duplicate_metadata":
        request_headers = list(request_headers.items()) + [
            ("X-IDE-Restore-Request", json.dumps(payload))
        ]
    if case == "type":
        request_headers["Content-Type"] = "application/zip"
    if case == "length":
        request_headers["Content-Length"] = "999"
    if case == "encoding":
        request_headers["Content-Encoding"] = "gzip"
    if case == "transfer":
        request_headers["Transfer-Encoding"] = "chunked"
    if case in {"short", "long"}:
        body = BODY[:-1] if case == "short" else BODY + b"x"
        request_headers["Content-Length"] = str(len(BODY))
    if case == "digest":
        body = b"x" * len(BODY)
    response = client.post("/workspaces/allocations/restore", content=body, headers=request_headers)
    assert response.status_code in {422, 503}
    assert registry.create_restored.await_count == 0
    assert all(file.closed for file in state.files)


@pytest.mark.parametrize(
    "failure,status",
    [
        (AllocationPending(), 409),
        (AllocationConflict(), 409),
        (AllocationExpired(), 410),
        (TooManyWorkspaces(), 413),
        (IsolationUnverified("private"), 500),
        (DriverError("private"), 502),
        (BundleFailure(), 503),
        (TimeoutError(), 503),
    ],
)
def test_restore_failure_is_bounded_and_never_automatically_replayed(setup, failure, status):
    client, payload, state, registry = setup
    state.failure = failure
    response = client.post(
        "/workspaces/allocations/restore", content=BODY, headers=headers(payload)
    )
    assert response.status_code == status and "private" not in response.text
    assert registry.create_restored.await_count == 1
    assert state.files[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["disconnect", "cancel", "expired"])
async def test_interrupted_upload_closes_local_spool_without_publishing_or_allocating(
    setup, interruption, monkeypatch
):
    client, payload, state, registry = setup
    waiting = asyncio.Event()
    receives = 0

    async def receive():
        nonlocal receives
        receives += 1
        if receives == 1:
            if interruption == "expired":
                monkeypatch.setattr(
                    "application.allocations.time.time",
                    lambda: payload["allocation"]["expires_at"] + 1,
                )
            return {"type": "http.request", "body": BODY, "more_body": interruption != "expired"}
        waiting.set()
        if interruption == "cancel":
            await asyncio.Future()
        return {"type": "http.disconnect"}

    request = Request(
        {
            "type": "http",
            "headers": [
                (b"content-type", b"application/octet-stream"),
                (b"content-length", str(len(BODY)).encode()),
            ],
        },
        receive=receive,
    )
    handler = next(
        route.endpoint
        for route in client.app.routes
        if route.path == "/workspaces/allocations/restore"
    )
    task = asyncio.create_task(
        handler(request, authorization="Bearer service", metadata=[json.dumps(payload)])
    )
    if interruption == "cancel":
        await asyncio.wait_for(waiting.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        response = await task
        assert response.status_code == (410 if interruption == "expired" else 503)
    assert registry.create_restored.await_count == 0
    assert len(state.files) == 1 and state.files[0].closed


@pytest.mark.parametrize("valid", [False, True])
def test_http_restore_uses_real_registry_and_format_verification_without_replacing_a_live_repo(
    setup, monkeypatch, valid
):
    client, payload, state, wrapper = setup
    monkeypatch.setenv("WORKSPACE_OWNER_SECRET", "isolated-http-restore-test-secret")
    body = capsule() if valid else BODY
    payload["snapshot"] = {"sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
    fake = lifecycle_driver()
    exchanges = []

    @asynccontextmanager
    async def exchange(ref, program, **kwargs):
        header = json.loads(kwargs["header"])
        exchanges.append(header["operation"])
        if header["operation"] == "restore":
            assert kwargs["source"].read() == body
            report = {"status": "ok", "operation": "restore", "entries": 1}
        else:
            assert header["operation"] in {"seal", "receipt"} and kwargs["source"] is None
            report = {"status": "ok", "operation": header["operation"], "ready": True}
        with io.BytesIO(b"") as source:
            yield BinaryExecReply(
                0,
                source,
                0,
                hashlib.sha256(b"").hexdigest(),
                json.dumps(report, separators=(",", ":")).encode(),
            )

    fake.exec_binary = exchange
    registry = WorkspaceRegistry(fake, max_workspaces=1)
    wrapper.create_restored = registry.create_restored
    wrapper.lookup_allocation = registry.lookup_allocation
    wrapper.allocation_token = registry.allocation_token
    response = client.post(
        "/workspaces/allocations/restore", content=body, headers=headers(payload)
    )
    if not valid:
        assert response.status_code == 413 and registry.count() == 0
        fake.destroy.assert_awaited_once()
        assert not exchanges
    else:
        assert response.status_code == 200 and registry.count() == 1
        assert exchanges == ["restore", "seal"]
        original = response.json()
        fresh = WorkspaceRegistry(fake, max_workspaces=1)
        assert asyncio.run(fresh.reconcile()) == 1
        wrapper.create_restored = fresh.create_restored
        wrapper.lookup_allocation = fresh.lookup_allocation
        wrapper.allocation_token = fresh.allocation_token
        registry = fresh
        expected = ["restore", "seal", "receipt"]
        metadata = {key: value for key, value in payload.items() if key != "limits"}
        observed = client.post("/workspaces/allocations/restore/lookup", headers=headers(metadata))
        assert observed.json() == original and exchanges == expected
        assert type(observed.json()["expires_at"]) is int
        replay = client.post(
            "/workspaces/allocations/restore", content=body, headers=headers(payload)
        )
        assert replay.json() == original
        assert type(replay.json()["expires_at"]) is int
        assert exchanges == expected and fake.create.await_count == 1
        changed = body + b"x"
        payload["snapshot"] = {"sha256": hashlib.sha256(changed).hexdigest(), "size": len(changed)}
        conflict = client.post(
            "/workspaces/allocations/restore", content=changed, headers=headers(payload)
        )
        assert conflict.status_code == 409 and registry.count() == 1
        assert exchanges == expected and fake.destroy.await_count == 0
    assert all(file.closed for file in state.files)
