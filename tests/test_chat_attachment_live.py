"""Opt-in dev acceptance: real chat intake, durable Library, passive Work.

Uses an isolated authenticated dev account with operator-verified graph indexing disabled.
The explicit opt-in acknowledges that precondition; it is not evidence of configuration.
No fault injection or permission to enable background model calls.
Do not pass a production endpoint or an ordinary user's token.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
import pytest
from websockets.asyncio.client import connect

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        os.getenv("E2E_LIVE_WORK_HUB") != "1" or not os.getenv("E2E_AUTH_TOKEN"),
        reason="requires isolated dev account and explicit live opt-in",
    ),
]


async def _request(client, method, path, **kwargs):
    try:
        return await client.request(method, path, **kwargs)
    except httpx.HTTPError:
        raise RuntimeError("attachment_http_unavailable") from None


@asynccontextmanager
async def _socket(url):
    try:
        async with connect(
            url, additional_headers={"Cookie": f"auth_token={os.environ['E2E_AUTH_TOKEN']}"}
        ) as socket:
            yield socket
    except Exception:
        raise RuntimeError("attachment_socket_unavailable") from None


async def test_chat_attachment_is_durable_idempotent_and_does_not_activate_workspace(monkeypatch):
    assert os.getenv("S37_UNMETERED_UPLOAD_CONFIRMED") == "1", (
        "verify deployed upload graph indexing is disabled before this unmetered smoke"
    )
    for name in (
        "httpx",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "websockets.client",
    ):
        monkeypatch.setattr(logging.getLogger(name), "disabled", True)
    base_url = os.getenv("S37_BACKEND_URL", "http://localhost:8001")
    endpoint = httpx.URL(base_url)
    assert endpoint.host in {"localhost", "127.0.0.1"}, "dev-only acceptance endpoint"
    assert endpoint.scheme == "http", "dev-only acceptance endpoint"
    content = b"# Synthetic attachment\n\nMaterial for a dev acceptance check.\n"
    name = f"s37-material-{uuid4().hex}.md"
    intent = str(uuid4())
    async with httpx.AsyncClient(
        base_url=base_url,
        cookies={"auth_token": os.environ["E2E_AUTH_TOKEN"]},
        timeout=60,
    ) as client:
        created = await _request(
            client, "POST", "/api/chats/", json={"title": "S37 attachment acceptance"}
        )
        assert created.status_code == 201, "thread_create_failed"
        thread_id = str(UUID(created.json()["thread_id"]))
        file_id = ""
        try:
            first = await _request(client, "GET", f"/api/chats/{thread_id}/work")
            assert first.status_code == 200, "initial_snapshot_failed"
            assert first.json()["workspace"]["state"] == "absent"
            file_id = ""
            for _ in range(2):
                uploaded = await _request(
                    client,
                    "POST",
                    "/api/chats/upload",
                    data={"thread_id": thread_id, "upload_intent_id": intent},
                    files={"file": (name, content, "text/markdown")},
                )
                assert uploaded.status_code == 200, "chat_upload_failed"
                payload = uploaded.json()
                current_id = str(UUID(payload["file_id"]))
                assert payload["content_sha256"] == hashlib.sha256(content).hexdigest()
                assert content.decode().strip() in payload["extracted_text"]
                if file_id:
                    assert current_id == file_id, "upload_intent_not_idempotent"
                file_id = current_id
            snapshot = await _request(client, "GET", f"/api/chats/{thread_id}/work")
            assert snapshot.status_code == 200, "final_snapshot_failed"
            work = snapshot.json()
            assert work["workspace"]["state"] == "absent", "passive_intake_activated_workspace"
            items = work["library"]["items"]
            matches = [item for item in items if item.get("file_id") == file_id]
            assert len(matches) == 1, "library_missing_or_duplicate_attachment"
            item = matches[0]
            assert item["name"] == name
            assert not ({"url", "file_url", "key", "storage_key", "file_key"} & item.keys())
            downloaded = await _request(
                client, "GET", f"/api/service/files/v1/{file_id}/download", follow_redirects=True
            )
            assert downloaded.status_code == 200, "attachment_download_failed"
            assert downloaded.content == content, "attachment_download_content_mismatch"
            assert hashlib.sha256(downloaded.content).hexdigest() == payload["content_sha256"]
            # Invalid confirmation is a non-metered way to exercise attachment
            # registration and disconnect cleanup through the actual WS handler.
            async with (
                _socket(f"ws://{endpoint.host}:{endpoint.port}/api/chats/{thread_id}/ws") as socket,
                asyncio.timeout(15),
            ):
                await socket.send(
                    json.dumps(
                        {
                            "type": "message",
                            "id": str(uuid4()),
                            "text": "",
                            "confirm_offer_id": uuid4().hex,
                            "file_ids": [file_id],
                        }
                    )
                )
                while True:
                    event = json.loads(await socket.recv())
                    if event.get("type") == "error":
                        break
                    assert event.get("type") != "job_created", "invalid_offer_started_job"
            after_disconnect = await _request(client, "GET", f"/api/chats/{thread_id}/work")
            assert after_disconnect.status_code == 200, "disconnect_snapshot_failed"
            assert any(
                row.get("file_id") == file_id for row in after_disconnect.json()["library"]["items"]
            ), "disconnect_deleted_library_source"
        finally:
            try:
                if file_id:
                    removed_file = await _request(
                        client, "DELETE", f"/api/service/files/v1/delete/{file_id}"
                    )
                    assert removed_file.status_code in {200, 204}, "fixture_file_cleanup_failed"
                    absent = await _request(client, "GET", f"/api/service/files/v1/{file_id}")
                    assert absent.status_code == 404, "fixture_file_still_visible"
            finally:
                removed = await _request(client, "DELETE", f"/api/chats/{thread_id}")
                assert removed.status_code in {200, 204}, "fixture_thread_cleanup_failed"
