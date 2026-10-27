"""The fixture discards dispatch success only after actual GO, exactly once."""

import json

import pytest

from scripts.harness.live.workspace_server import DispatchAckBoundary


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 409, 503])
async def test_dispatch_boundary_never_replays_or_replaces_the_executor(status):
    effects = []

    async def handler(scope, receive, send):
        payload = json.loads((await receive())["body"])
        effects.append(payload["action"])
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b'{"running":true}'})

    boundary = DispatchAckBoundary(handler, enabled=True)
    for action, expected in [("create", status), ("dispatch", 503), ("status", status)]:
        observed = []

        async def receive(selected=action):
            return {
                "type": "http.request",
                "body": json.dumps({"action": selected, "operation_id": "fixture"}).encode(),
            }

        async def send(message, output=observed):
            assert effects
            output.append(message)

        await boundary({"type": "http", "path": "/workspaces/fixture/ide/commands"}, receive, send)
        assert observed[0]["status"] == (expected if status == 200 else status)
    assert effects == ["create", "dispatch", "status"]
    assert boundary.lost == int(status == 200)
