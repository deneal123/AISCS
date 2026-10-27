import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from service.services.simulations import api, tasks
from service.shared.security.origins import allowed_cors_origins, websocket_origin_allowed


def policy(origins=None, mode="prod"):
    return SimpleNamespace(
        cors=SimpleNamespace(allow_origins=origins or []), auth=SimpleNamespace(auth_mode=mode)
    )


@pytest.mark.parametrize(
    "origin,allowed",
    [
        (None, True),
        ("https://aiscs.example.test", True),
        ("https://aiscs.example.test:443", True),
        ("https://aiscs.example.test:8445", False),
        ("http://aiscs.example.test", False),
        ("https://aiscs.example.test.evil.test", False),
        ("https://aiscs.example.test@evil.test", False),
        ("https://aiscs.example.test/path", False),
        ("https://aiscs.example.test?query=yes", False),
        ("https://aiscs.example.test#fragment", False),
        ("https://aiscs.example.test:invalid", False),
        ("null", False),
        ("", False),
        ("*", False),
    ],
)
def test_browser_websocket_uses_exact_credentialed_origin_policy(origin, allowed):
    assert websocket_origin_allowed(origin, policy(["https://aiscs.example.test"])) is allowed


def test_websocket_and_http_share_development_fallback_without_production_wildcards():
    development = policy(mode="dev")
    for origin in allowed_cors_origins(development):
        assert websocket_origin_allowed(origin, development)
    assert not websocket_origin_allowed("http://localhost:8095", development)
    assert not websocket_origin_allowed("https://any.test", policy(["*"]))
    assert not websocket_origin_allowed("http://localhost:3000", policy())


def test_wrong_browser_origin_is_denied_before_cookie_or_database_access(monkeypatch):
    authenticate = Mock(side_effect=AssertionError("must_not_authenticate"))
    monkeypatch.setattr(api, "config", policy(["https://aiscs.example.test"]))
    monkeypatch.setattr(api, "check_auth", authenticate)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(
                f"/api/simulations/v1/runs/{uuid4()}/events",
                headers={"origin": "https://untrusted.test"},
            ):
                pass
    assert error.value.code == 1008
    authenticate.assert_not_called()


@pytest.mark.asyncio
async def test_unresponsive_event_cache_does_not_hold_the_scientific_worker(monkeypatch):
    async def unavailable(*args, **kwargs):
        await asyncio.Event().wait()

    redis = SimpleNamespace(xadd=unavailable, expire=AsyncMock(), setex=AsyncMock())
    monkeypatch.setattr(tasks, "logger", Mock())
    await asyncio.wait_for(tasks.emit(SimpleNamespace(redis_client=redis), uuid4(), "running"), 2)
    redis.expire.assert_not_awaited()
    redis.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejected_result_retains_durable_cleanup_intent_when_executor_is_unreachable(
    monkeypatch,
):
    touch = AsyncMock(return_value=False)
    client = SimpleNamespace(post=AsyncMock(side_effect=httpx.ConnectError("offline")))

    @asynccontextmanager
    async def factory():
        yield client

    monkeypatch.setattr(tasks, "touch", touch)
    monkeypatch.setattr(tasks, "generator_client", factory)
    run_id, attempt, claim = uuid4(), uuid4(), uuid4()
    infra = object()
    await tasks.reject_result(infra, run_id, claim, attempt, "a" * 64, "artifact_integrity")
    touch.assert_awaited_once_with(
        infra,
        run_id,
        claim,
        "failed",
        result={"executor_discard_pending": True},
        error="invalid_executor_manifest:artifact_integrity",
    )
    assert client.post.await_args.args[0].endswith(f"/{attempt}/discard")


@pytest.mark.asyncio
@pytest.mark.parametrize("same_attempt", [True, False])
async def test_cleanup_confirmation_clears_only_its_terminal_attempt(same_attempt):
    attempt = uuid4()
    run = SimpleNamespace(
        state="failed",
        attempt_id=attempt if same_attempt else uuid4(),
        result={"executor_discard_pending": True},
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one=lambda: run)),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def context():
        yield session

    infra = SimpleNamespace(pg_connector=SimpleNamespace(get_session_context=context))
    response = httpx.Response(
        200, json={}, request=httpx.Request("POST", "http://executor/discard")
    )
    client = SimpleNamespace(post=AsyncMock(return_value=response))
    await tasks.confirm_discard(infra, client, uuid4(), attempt, "a" * 64)
    assert run.result["executor_discard_pending"] is not same_attempt
    assert session.commit.await_count == int(same_attempt)


@pytest.mark.asyncio
async def test_maintenance_retries_terminal_discard_separately_from_completed_ack(monkeypatch):
    pending = (uuid4(), uuid4(), "a" * 64)
    empty_rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                empty_rows,
                SimpleNamespace(all=lambda: []),
                SimpleNamespace(all=lambda: [pending]),
            ]
        ),
        commit=AsyncMock(),
    )

    @asynccontextmanager
    async def context():
        yield session

    infra = SimpleNamespace(
        pg_connector=SimpleNamespace(get_session_context=context, close=AsyncMock()),
        redis_client=None,
    )
    client = object()

    @asynccontextmanager
    async def factory():
        yield client

    discard, ack = AsyncMock(), AsyncMock()
    monkeypatch.setattr(tasks, "build_infra", lambda _: infra)
    monkeypatch.setattr(tasks, "generator_client", factory)
    monkeypatch.setattr(tasks, "confirm_discard", discard)
    monkeypatch.setattr(tasks, "acknowledge_result", ack)
    await tasks.recover()
    discard.assert_awaited_once_with(infra, client, *pending)
    ack.assert_not_awaited()
    infra.pg_connector.close.assert_awaited_once()
