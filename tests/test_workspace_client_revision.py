"""Revision preflight for coordinated agent mutations."""

from __future__ import annotations

import httpx
import pytest

from service.domain.tools import workspace_client


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["files/write", "revert"])
async def test_agent_mutation_fetches_and_forwards_current_revision(monkeypatch, mutation) -> None:
    seen: list[tuple[str, dict]] = []

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, json, headers):
            seen.append((str(url), dict(json)))
            if str(url).endswith("/view"):
                return httpx.Response(200, json={"revision": "revision-current"})
            return httpx.Response(200, json={"written": True, "reverted": True})

    monkeypatch.setattr(
        workspace_client,
        "_settings",
        lambda: ("http://workspace:8080", 30.0, True),
    )
    monkeypatch.setattr(workspace_client.httpx, "AsyncClient", Client)
    ref = {
        "workspace_id": "workspace-opaque",
        "token": "opaque-token",
        "user_id": "user-opaque",
        "coordination_capability": "opaque-capability",
    }
    payload = {"path": "note.txt", "content": "safe"}
    if mutation == "revert":
        payload = {"ref": "abc123", "path": ""}

    await workspace_client.call(ref, mutation, payload)

    assert len(seen) == 2
    assert seen[0][0].endswith("/view")
    assert seen[1][1]["expected_revision"] == "revision-current"
    assert "coordination_capability" in seen[1][1]


@pytest.mark.asyncio
async def test_read_does_not_add_a_revision_round_trip(monkeypatch) -> None:
    seen: list[str] = []

    class Client:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, url, *, json, headers):
            seen.append(str(url))
            return httpx.Response(200, json={"content": "safe", "revision": "r1"})

    monkeypatch.setattr(
        workspace_client,
        "_settings",
        lambda: ("http://workspace:8080", 30.0, True),
    )
    monkeypatch.setattr(workspace_client.httpx, "AsyncClient", Client)

    await workspace_client.call(
        {
            "workspace_id": "workspace-opaque",
            "token": "opaque-token",
            "user_id": "user-opaque",
            "coordination_capability": "opaque-capability",
        },
        "files/read",
        {"path": "note.txt"},
    )

    assert len(seen) == 1 and seen[0].endswith("/files/read")
