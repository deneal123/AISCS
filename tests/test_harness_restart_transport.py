"""Журнал double переживает замену процесса без production-памяти или сетевых вызовов."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.harness_live.restart import RefuseRecoveredRuns, restore_transport


def state():
    return {
        "completions": 4,
        "tool_names": ["ide_write_file"],
        "blocked_requests": 0,
        "oauth": 1,
        "tool_states": {"ide_write_file": "SYNTHETIC_PRIVATE_STATE"},
    }


def test_restart_restores_only_the_transport_double_state_and_consumes_the_envelope(monkeypatch):
    saved = state()
    monkeypatch.setenv("HARNESS_ACCEPTANCE_TRANSPORT_STATE", json.dumps(saved))
    provider = SimpleNamespace()
    restore_transport(provider)
    assert vars(provider) == saved
    assert "HARNESS_ACCEPTANCE_TRANSPORT_STATE" not in __import__("os").environ
    provider.completions += 1
    restore_transport(provider)
    assert provider.completions == 5


@pytest.mark.parametrize(
    "change",
    [
        {"completions": True},
        {"completions": -1},
        {"oauth": 101},
        {"headers": {"Authorization": "PRIVATE_TOKEN"}},
        {"tool_names": "not-a-list"},
    ],
)
def test_bad_envelope_cannot_turn_into_runtime_provider_settings(monkeypatch, change):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_TRANSPORT_STATE", json.dumps({**state(), **change}))
    provider = SimpleNamespace()
    with pytest.raises(AssertionError):
        restore_transport(provider)
    assert not vars(provider)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "restarted,enabled,path,refused",
    [
        ("1", "after_write", "/run", True),
        ("0", "after_write", "/run", False),
        ("1", "false", "/run", False),
        ("1", "after_write", "/__harness_acceptance__/instance", False),
        ("0", "before_dispatch", "/run", True),
    ],
)
async def test_acceptance_fault_refuses_only_resumed_runs(
    monkeypatch, restarted, enabled, path, refused
):
    monkeypatch.setenv("HARNESS_ACCEPTANCE_AGENTS_RESTARTED", restarted)
    monkeypatch.setenv("HARNESS_ACCEPTANCE_RESTART_EXHAUSTED", enabled)
    app, receive, send = AsyncMock(), AsyncMock(), AsyncMock()
    scope = {"type": "http", "path": path}
    await RefuseRecoveredRuns(app)(scope, receive, send)
    if refused:
        app.assert_not_awaited()
        assert send.call_args_list[0].args[0]["status"] == 503
        assert send.call_args_list[1].args[0]["body"] == b""
    else:
        app.assert_awaited_once_with(scope, receive, send)
        send.assert_not_awaited()
