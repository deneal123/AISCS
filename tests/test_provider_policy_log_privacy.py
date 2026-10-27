"""Provider-policy degradation retains its state without logging private payloads."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from service.infrastructure import provider_policy_store as policy

MARKER = "private-provider-body-https://secret.invalid/path?credential=hidden"


@pytest.fixture(autouse=True)
def capture_policy_logger(monkeypatch, caplog):
    # App initialization intentionally stops service logs at its own handler.
    # Capture this boundary directly, independent of suite/import order.
    monkeypatch.setattr(policy.logger, "handlers", [caplog.handler])
    monkeypatch.setattr(policy.logger, "propagate", False)
    monkeypatch.setattr(policy.logger, "disabled", False)
    monkeypatch.setattr(policy.logger, "level", logging.DEBUG)


@pytest.fixture
def isolated_policy(monkeypatch, caplog):
    monkeypatch.setattr(policy, "_BLOCKED", {})
    monkeypatch.setattr(policy, "_repo", None)
    monkeypatch.setattr(policy, "_get_redis", lambda: None)
    caplog.set_level(logging.DEBUG, logger=policy.__name__)


def _assert_safe(caplog):
    records = [record for record in caplog.records if record.name == policy.__name__]
    assert records
    assert MARKER not in caplog.text
    for record in records:
        assert record.exc_info is None and record.stack_info is None
        assert record.component == "provider_policy"
        assert isinstance(record.failure_code, str)
        assert MARKER not in repr(record.__dict__)


def test_unknown_diagnostic_code_cannot_become_a_payload_field(caplog):
    caplog.set_level(logging.DEBUG, logger=policy.__name__)
    policy._diagnostic(logging.WARNING, MARKER)
    _assert_safe(caplog)
    assert caplog.records[-1].failure_code == "policy_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prime", "persist"])
async def test_database_failure_logs_no_exception_body(stage, isolated_policy, monkeypatch, caplog):
    repo = SimpleNamespace(
        get_all=AsyncMock(side_effect=OSError(MARKER)),
        upsert=AsyncMock(side_effect=OSError(MARKER)),
    )
    monkeypatch.setattr(policy, "_repo", repo)
    policy._BLOCKED["gigachat"] = "unavailable"
    if stage == "prime":
        await policy.prime()
    else:
        await policy._persist_db()
    assert policy._BLOCKED == {"gigachat": "unavailable"}
    _assert_safe(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["seed", "block", "clear", "read"])
async def test_redis_failure_keeps_existing_fallback_without_traceback(
    stage, isolated_policy, monkeypatch, caplog
):
    redis = SimpleNamespace(
        set=Mock(side_effect=OSError(MARKER)),
        delete=Mock(side_effect=OSError(MARKER)),
        mget=Mock(side_effect=OSError(MARKER)),
    )
    monkeypatch.setattr(policy, "_get_redis", lambda: redis)
    policy._BLOCKED["gigachat"] = "unavailable"
    if stage == "seed":
        monkeypatch.setattr(
            policy,
            "_repo",
            SimpleNamespace(
                get_all=AsyncMock(
                    return_value={"provider_blocked": {"gigachat": {"reason": "unavailable"}}}
                )
            ),
        )
        await policy.prime()
    elif stage == "block":
        await policy.set_blocked("gigachat", "unavailable")
    elif stage == "clear":
        await policy.clear_blocked("gigachat")
    else:
        assert await policy.blocked_providers() == {"gigachat"}
    assert policy._BLOCKED == ({} if stage == "clear" else {"gigachat": "unavailable"})
    _assert_safe(caplog)


@pytest.mark.asyncio
async def test_unknown_name_and_raw_health_reason_are_not_log_labels(
    isolated_policy, monkeypatch, caplog
):
    await policy.set_blocked(MARKER, MARKER)
    assert policy._BLOCKED[MARKER.lower()] == MARKER
    await policy.clear_blocked(MARKER)
    monkeypatch.setattr(
        policy,
        "_repo",
        SimpleNamespace(
            get_all=AsyncMock(return_value={"provider_blocked": {MARKER: {"reason": MARKER}}})
        ),
    )
    await policy.prime()
    assert policy._BLOCKED[MARKER] == MARKER
    _assert_safe(caplog)


def test_redis_client_initialization_failure_has_only_bounded_diagnostic(monkeypatch, caplog):
    import redis

    monkeypatch.setattr(policy, "_redis", None)
    monkeypatch.setattr(policy, "_redis_ready", False)
    monkeypatch.setattr(
        policy, "config", SimpleNamespace(redis=SimpleNamespace(enabled=True, dsn=MARKER))
    )
    monkeypatch.setattr(redis.Redis, "from_url", Mock(side_effect=OSError(MARKER)))
    caplog.set_level(logging.DEBUG, logger=policy.__name__)
    assert policy._get_redis() is None
    _assert_safe(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prime", "persist"])
async def test_cancellation_propagates_without_logging_or_rewriting_state(
    stage, isolated_policy, monkeypatch, caplog
):
    monkeypatch.setattr(
        policy,
        "_repo",
        SimpleNamespace(
            get_all=AsyncMock(side_effect=asyncio.CancelledError()),
            upsert=AsyncMock(side_effect=asyncio.CancelledError()),
        ),
    )
    policy._BLOCKED["gigachat"] = "unavailable"
    with pytest.raises(asyncio.CancelledError):
        await (policy.prime() if stage == "prime" else policy._persist_db())
    assert policy._BLOCKED == {"gigachat": "unavailable"}
    assert not caplog.records
