"""Bounded lifecycle contract for the opt-in GigaChat workspace fixture."""

from __future__ import annotations

import pytest

from service.utils import gigachat_workspace_fixture as fixture


def test_cleanup_scope_accepts_only_matching_smoke_identity() -> None:
    valid = {"thread_id": "s25-smoke-abc", "user_id": "s25-smoke-abc"}

    assert fixture._is_owned_fixture(valid)
    assert not fixture._is_owned_fixture({**valid, "thread_id": "normal-thread"})
    assert not fixture._is_owned_fixture({**valid, "user_id": "s25-smoke-other"})


@pytest.mark.asyncio
async def test_provision_mints_private_agent_capability(monkeypatch) -> None:
    async def ensure(_redis, thread_id, user_id):
        assert thread_id == user_id
        return {
            "workspace_id": "workspace-opaque",
            "token": "owner-private",
            "thread_id": thread_id,
            "user_id": user_id,
            "expires_at": 1000.0,
        }

    captured = {}

    def mint(workspace_id, **kwargs):
        captured.update({"workspace_id": workspace_id, **kwargs})
        return "capability-private"

    monkeypatch.setattr(fixture, "ensure_workspace_explicit", ensure)
    monkeypatch.setattr(fixture, "mint_capability", mint)

    payload = await fixture._provision(object())

    ref = payload["workspace_ref"]
    assert fixture._is_owned_fixture(ref)
    assert ref["coordination_capability"] == "capability-private"
    assert captured["role"] == "agent"
    assert captured["workspace_id"] == "workspace-opaque"
    assert payload["marker"].startswith("s25-")
