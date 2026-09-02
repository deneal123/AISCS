"""The Work Hub read model is captured inside one workspace operation guard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from presentation import workspace_routes


class _Registry:
    def __init__(self) -> None:
        self.depth = 0
        self.depths: list[int] = []
        self.item = SimpleNamespace(
            policy=SimpleNamespace(root="/workspace", exec_timeout_sec=10),
            recovered=True,
        )

    def get(self, workspace_id: str, user_id: str, token: str):
        assert (workspace_id, user_id, token) == ("workspace-1", "owner", "opaque-token")
        return self.item

    @asynccontextmanager
    async def operation(self, item):
        assert item is self.item
        self.depth += 1
        try:
            yield item
        finally:
            self.depth -= 1

    async def exec_raw(self, item, command: str, **_kwargs):
        assert item is self.item
        self.depths.append(self.depth)
        if "git log" in command:
            stdout = "abc123\t2026-08-31T12:00:00+03:00\tuser_edit"
        elif "rev-parse HEAD" in command:
            stdout = "revision-1"
        else:
            stdout = "dir\t0\t/workspace/src\nfile\t12\t/workspace/src/main.py"
        return SimpleNamespace(stdout=stdout, truncated=False)


@pytest.mark.asyncio
async def test_view_returns_tree_history_and_revision_from_one_guard(monkeypatch) -> None:
    registry = _Registry()
    monkeypatch.setattr(workspace_routes, "registry", registry)
    monkeypatch.setattr(workspace_routes, "SERVICE_KEY", "service-key")

    result = await workspace_routes.workspace_view(
        "workspace-1",
        workspace_routes.FileRequest(user_id="owner", token="opaque-token"),
        authorization="Bearer service-key",
    )

    assert registry.depths == [1, 1, 1]
    assert result["revision"] == "revision-1"
    assert result["history"][0]["message"] == "user_edit"
    assert result["entries"][1]["path"] == "/workspace/src/main.py"
    assert result["recovered"] is True
