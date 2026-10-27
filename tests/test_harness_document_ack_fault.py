"""HTTP double теряет ACK только после успешного настоящего handler."""

import json

import httpx
import pytest

from scripts.harness.live.workspace_server import DocumentAckBoundary


@pytest.mark.asyncio
@pytest.mark.parametrize("action,key", [("proposals", "proposal_id"), ("builds", "build_id")])
async def test_document_ack_fault_loses_one_committed_response_not_execution(action, key):
    committed = []

    async def handler(scope, receive, send):
        body = await receive()
        committed.append(json.loads(body["body"]))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps({key: "stable-id"}).encode(),
            }
        )

    boundary = DocumentAckBoundary(handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary), base_url="http://test"
    ) as client:
        first = await client.post("/workspaces/own/documents/" + action, json={"operation": "same"})
        second = await client.post(
            "/workspaces/own/documents/" + action, json={"operation": "same"}
        )
    assert first.status_code == 503 and second.json() == {key: "stable-id"}
    assert committed == [{"operation": "same"}] * 2
    assert boundary.metrics()["lost"][action] == 1
    assert boundary.metrics()["identities"][action] == 1


@pytest.mark.asyncio
async def test_invalid_request_does_not_consume_the_committed_ack_fault():
    async def handler(scope, receive, send):
        await send({"type": "http.response.start", "status": 422, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    boundary = DocumentAckBoundary(handler)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=boundary), base_url="http://test"
    ) as client:
        response = await client.post("/workspaces/own/documents/builds", json={})
    assert response.status_code == 422 and boundary.metrics()["lost"]["builds"] == 0
